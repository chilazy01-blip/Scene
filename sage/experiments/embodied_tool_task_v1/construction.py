"""A single geometric clearance rule followed by endpoints, then fixed paths."""
from pathlib import Path
from xml.etree import ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_scene_bridge.adapter import add_robot
from sage.experiments.embodied_scene_bridge.environment import owners
from sage.experiments.embodied_planner_m2_v2.contacts import ContactPolicy
from sage.experiments.embodied_simdata_v0.controller import PandaController
from sage.experiments.embodied_task_scene_v1.robot import matrix,set_target
from sage.experiments.embodied_scene_v1.package import set_pose,vec
from sage.experiments.embodied_task_generation_v1.planner import corners


def clearance_gap(tool_bounds,support_bounds,margin,minimum):
    """Conservative XY overlap; derive one vertical translation without search."""
    gap=float(minimum);witnesses=[]
    for name,bounds in tool_bounds.items():
        bounds=np.asarray(bounds);support=np.asarray(support_bounds)
        overlap=np.all((bounds[0,:2]-margin<=support[:,1,:2])&(bounds[1,:2]+margin>=support[:,0,:2]),axis=1)
        if overlap.any():
            index=np.flatnonzero(overlap)[np.argmax(support[overlap,1,2])]
            needed=float(support[index,1,2]+margin-bounds[0,2]);gap=max(gap,needed)
            witnesses.append(dict(tool=name,support_index=int(index),required_gap_m=needed))
    return gap,witnesses


def geom_points(model,data,gid):
    import mujoco
    typ=model.geom_type[gid]
    if typ==mujoco.mjtGeom.mjGEOM_MESH:
        mid=int(model.geom_dataid[gid]);a=int(model.mesh_vertadr[mid]);n=int(model.mesh_vertnum[mid]);points=model.mesh_vert[a:a+n]
    elif typ==mujoco.mjtGeom.mjGEOM_BOX:points=corners(2*model.geom_size[gid])
    else:raise ValueError('unsupported_tool_or_support_geom:'+model.geom(gid).name)
    return points@data.geom_xmat[gid].reshape(3,3).T+data.geom_xpos[gid]


def templates(model,data,ctrl,width,settings):
    import mujoco
    fingers=[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]
    result={};max_error=0.
    for mode,gap in [('closed',width/2),('open',.04)]:
        poses=[]
        for q in [ctrl.qhome,ctrl.qhome+.01]:
            data.qpos[ctrl.qi]=q;data.qpos[fingers]=[gap,-gap];mujoco.mj_forward(model,data)
            origin=data.site_xpos[ctrl.site];rotation=data.site_xmat[ctrl.site].reshape(3,3)
            poses.append({name:(geom_points(model,data,model.geom(name).id)-origin)@rotation for name in settings['tool_geoms']})
        for name in poses[0]:max_error=max(max_error,float(np.max(abs(poses[0][name]-poses[1][name]))))
        result[mode]=poses[0]
    require(max_error<1e-8,'tool_not_rigid_to_grip_frame')
    return result,max_error


def construct(config,protocol):
    import mujoco
    config=Path(config);package=config/'package';task=read(package/'task.json');local=read(config/'local_contact/task.json')
    settings=protocol['tool_construction'];limits=protocol['robot']
    root=ET.parse(package/'model.xml').getroot();world=root.find('worldbody')
    sources=add_robot(root,package,np.asarray(task['support_pose']),{})
    ET.SubElement(world,'geom',name='robot_mount',type='box',pos='0 0 .01',size='.09 .09 .01',group='3',rgba='.2 .2 .2 1')
    source=package/'robot_unmounted.xml';ET.ElementTree(root).write(source,encoding='unicode')
    model=mujoco.MjModel.from_xml_path(str(source));data=mujoco.MjData(model);ctrl=PandaController(model,data)
    width=task['target_dimensions_m'][0];require(width+.01<=.08,'gripper_width_exceeds_range')
    tools,frame_error=templates(model,data,ctrl,width,settings)
    support=model.body(task['support_body']).id
    support_ids=[i for i in range(model.ngeom) if model.geom_bodyid[i]==support and (model.geom_contype[i] or model.geom_conaffinity[i])]
    require(bool(support_ids),'support_proxy_missing')
    support_bounds=np.array([[geom_points(model,data,i).min(0),geom_points(model,data,i).max(0)] for i in support_ids])
    start=np.asarray(task['start_pose_z_up']);goal=np.asarray(task['goal_pose_z_up']);candidates=[]
    for ordinal,roll in enumerate(settings['grasp_roll_degrees']):
        grip=matrix(start[:3,3]+start[:3,:3]@[0.,0.,task['target_dimensions_m'][2]/2-settings['grasp_offset_from_top_m']],
            start[:3,:3]@np.diag([1.,-1.,-1.])@Rotation.from_euler('x',roll,degrees=True).as_matrix())
        held=np.linalg.inv(grip)@start;at_goal=goal@np.linalg.inv(held);bounds={}
        for mode,geoms in tools.items():
            for name,points in geoms.items():
                worldpoints=points@at_goal[:3,:3].T+at_goal[:3,3];bounds[mode+':'+name]=np.array([worldpoints.min(0),worldpoints.max(0)])
        gap,witnesses=clearance_gap(bounds,support_bounds,settings['clearance_margin_m'],settings['minimum_release_gap_m'])
        candidates.append(dict(ordinal=ordinal,roll_degrees=roll,required_gap_m=gap,in_task_range=bool(gap<=settings['maximum_release_gap_m']),
            held_transform=held.tolist(),start_grip_pose=grip.tolist(),tool_bounds_at_goal={k:v.tolist() for k,v in bounds.items()},witnesses=witnesses,
            status='eligible_for_native_endpoint_checks' if gap<=settings['maximum_release_gap_m'] else 'conservative_tool_clearance_exceeds_task_gap'))
    np.savez_compressed(package/'TOOL_RULE_RAW.npz',support_bounds=support_bounds,**{mode+'__'+name:points for mode,geoms in tools.items() for name,points in geoms.items()})
    rule=dict(candidates=candidates,frame_invariance_error_m=frame_error,raw=reference(package/'TOOL_RULE_RAW.npz'),
        support_geoms=[model.geom(i).name for i in support_ids],maximum_gap_m=settings['maximum_release_gap_m'],
        scope='conservative distal-tool envelope against current support proxy; not source geometry or hardware feasibility')
    write_new(package/'TOOL_RULE.json',rule)
    policy=ContactPolicy(model,owners(model),task);owner=owners(model);bid=model.body('base').id;mount=model.geom('robot_mount').id
    target=model.body(task['target_body']).id;qi=int(model.jnt_qposadr[model.body_jntadr[target]])
    finger_qi=[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]
    support_pose=np.asarray(task['support_pose']);dims=np.ptp(np.asarray(task['support_bounds_local_m']),axis=0)
    dims[:2]+=2*protocol['selection']['surface_edge_inset_m'];w,l=dims[:2]
    offsets=[(-w/2+.11,0),(w/2-.11,0),(-w/2+.11,-l/4),(w/2-.11,-l/4),(-w/4,-l/2+.11),(w/4,-l/2+.11),(-w/4,l/2-.11),(w/4,l/2-.11)]
    checks=[];selected=None;ik_queries=path_checks=path_states=0
    def place(q,gap,held,phase):
        data.qpos[ctrl.qi]=q;data.qpos[finger_qi]=[gap,-gap];mujoco.mj_kinematics(model,data)
        attached=phase in ['lift','reorient','release','open']
        obj=matrix(data.site_xpos[ctrl.site].copy(),data.site_xmat[ctrl.site].reshape(3,3).copy())@held if attached else goal if phase=='retreat' else start
        set_target(data,qi,obj);mujoco.mj_forward(model,data)
    def violations(phase):return policy.violations(data,limits['max_static_penetration_m'],allow_fingers=phase not in ['home','pregrasp','retreat'],allow_support=phase in ['home','pregrasp','grasp','close','lift','retreat'])
    for grasp in sorted(candidates,key=lambda r:(r['required_gap_m'],r['ordinal'])):
        if not grasp['in_task_range'] or not task['geometry_passed']:continue
        held=np.asarray(grasp['held_transform']);grip=np.asarray(grasp['start_grip_pose'])
        pre=grip.copy();pre[2,3]+=.10;lift=start.copy();lift[2,3]+=limits['lift_m'];turn=goal.copy();turn[2,3]=max(start[2,3],goal[2,3])+limits['lift_m']
        release=goal.copy();release[2,3]+=grasp['required_gap_m'];release_grip=release@np.linalg.inv(held);retreat=release_grip.copy();retreat[2,3]+=.10
        poses=[('pregrasp',pre,.04),('grasp',grip,.04),('close',grip,width/2),('lift',lift@np.linalg.inv(held),width/2),
            ('reorient',turn@np.linalg.inv(held),width/2),('release',release_grip,width/2),('open',release_grip,.04),('retreat',retreat,.04)]
        for index,(x,y) in enumerate(offsets):
            xyz=support_pose[:3,3]+support_pose[:3,:3]@[x,y,0.];xyz[2]=support_pose[2,3]+local['maximum_support_height_local_m']+.02
            direction=support_pose[:3,3]-xyz;yaw=np.arctan2(direction[1],direction[0]);quat=[np.cos(yaw/2),0,0,np.sin(yaw/2)]
            model.body_pos[bid]=xyz;model.body_quat[bid]=quat;model.geom_pos[mount]=xyz-[0,0,.01]
            mujoco.mj_resetData(model,data);place(ctrl.qhome,.04,held,'home')
            row=dict(grasp_ordinal=grasp['ordinal'],mount_index=index,mount_position=xyz.tolist(),mount_quaternion=quat,endpoints=[],paths=[],status='checking')
            checks.append(row)
            try:
                bad=violations('home');row['home_violations']=bad;require(not bad,'home_collision')
                saved_group=model.geom_group[mount];model.geom_group[mount]=0;rays=[]
                try:
                    for dx,dy in [(0,0),(-.09,-.09),(-.09,.09),(.09,-.09),(.09,.09)]:
                        origin=xyz+support_pose[:3,:3]@[dx,dy,0.];origin[2]=xyz[2]-.02+.3;hit=np.array([-1],dtype=np.int32)
                        distance=mujoco.mj_ray(model,data,origin,np.array([0.,0.,-1.]),np.array([0,0,0,1,0,0],dtype=np.uint8),1,target,hit)
                        rays.append(bool(distance>=0 and owner.get(int(hit[0]))==task['support_body'] and abs(origin[2]-distance-(xyz[2]-.02))<=.015))
                finally:model.geom_group[mount]=saved_group
                row['mount_rays']=rays;require(all(rays),'mount_not_supported')
                q=ctrl.qhome.copy()
                for phase,wanted,gap in poses:
                    if phase not in ['close','open']:
                        require(ik_queries<limits['max_ik_queries_per_request'],'ik_budget');ik_queries+=1
                        ctrl.target_rot=wanted[:3,:3];q,residual=ctrl.ik(wanted[:3,3],q)
                    else:residual=0.
                    place(q,gap,held,phase);actual=matrix(data.site_xpos[ctrl.site].copy(),data.site_xmat[ctrl.site].reshape(3,3).copy())
                    pos=float(np.linalg.norm(actual[:3,3]-wanted[:3,3]));angle=float(np.rad2deg(Rotation.from_matrix(wanted[:3,:3]@actual[:3,:3].T).magnitude()));bad=violations(phase)
                    point=dict(phase=phase,q=q.tolist(),gap=gap,gripper_pose=wanted.tolist(),position_error_m=pos,orientation_error_deg=angle,violations=bad)
                    row['endpoints'].append(point)
                    require(pos<=limits['ik_position_tolerance_m'] and angle<=limits['ik_orientation_tolerance_deg'],'endpoint_ik:'+phase)
                    require(not bad,'endpoint_collision:'+phase)
                row['all_endpoints_passed']=True;require(path_checks<limits['maximum_path_checks_per_request'],'path_budget');path_checks+=1
                previous=ctrl.qhome.copy();previous_gap=.04
                for endpoint in row['endpoints']:
                    q=np.asarray(endpoint['q']);gap=endpoint['gap'];phase=endpoint['phase'];count=max(1,int(np.ceil(max(abs(q-previous))/limits['dense_joint_step_rad'])),int(np.ceil(abs(gap-previous_gap)/.005)))
                    require(count+1<=limits['max_path_states_per_segment'],'path_density_budget');bad=[]
                    for k in range(count+1):
                        place(previous+(q-previous)*k/count,previous_gap+(gap-previous_gap)*k/count,held,phase);path_states+=1;bad=violations(phase)
                        if bad:break
                    row['paths'].append(dict(phase=phase,checked=k+1,planned=count+1,violations=bad));require(not bad,'path_collision:'+phase)
                    previous=q;previous_gap=gap
                row['status']='preflight_passed';row['release_object_pose']=release.tolist();row['held_transform']=held.tolist();row['release_gap_m']=grasp['required_gap_m'];selected=row
                set_pose(world.find("body[@name='base']"),matrix(xyz,Rotation.from_quat(np.asarray(quat)[[1,2,3,0]]).as_matrix()))
                world.find("geom[@name='robot_mount']").set('pos',vec(xyz-[0,0,.01]));ET.ElementTree(root).write(package/'robot_mounted.xml',encoding='unicode')
            except ValueError as exc:row.update(status='rejected',reason=str(exc))
            write_new(package/('CANDIDATE_'+str(grasp['ordinal'])+'_'+str(index)+'.json'),row)
            if selected is not None:break
        if selected is not None:break
    result=dict(passed=selected is not None,selected=selected,candidates=checks,tool_rule=reference(package/'TOOL_RULE.json'),
        local_geometry_passed=task['geometry_passed'],new_ik_queries=ik_queries,new_path_checks=path_checks,path_states=path_states,new_physics_steps=0,
        status='preflight_passed' if selected else 'fixed_tool_task_preflight_rejected',robot_sources=sources,
        source_mesh_interference='unknown',no_hardware_feasibility_claim=True)
    write_new(package/'PREFLIGHT.json',result);return result
