"""Finite robot geometry/path preflight with distinct object start and goal poses."""
from pathlib import Path
from xml.etree import ElementTree as ET
import shutil,time
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.embodied_scene_bridge.adapter import add_robot
from sage.experiments.embodied_scene_bridge.environment import owners
from sage.experiments.embodied_scene_v1.package import set_pose,vec
from sage.experiments.embodied_simdata_v0.controller import PandaController
from sage.experiments.embodied_planner_m2_v2.contacts import ContactPolicy


def matrix(position,rotation):
    result=np.eye(4);result[:3,:3]=rotation;result[:3,3]=position;return result


def set_target(data,qi,pose):
    data.qpos[qi:qi+3]=pose[:3,3];data.qpos[qi+3:qi+7]=Rotation.from_matrix(pose[:3,:3]).as_quat()[[3,0,1,2]]


def preflight(config,protocol):
    import mujoco
    config=Path(config);package=config/'package';task=read(package/'task.json');limits=protocol['robot']
    if not task['geometry_passed']:return dict(passed=False,status='skipped_geometry_gate',new_physics_steps=0,candidates=[])
    output=config/'robot';output.mkdir(exist_ok=False);shutil.copytree(package/'assets',output/'assets')
    shutil.copyfile(package/'target_collision.stl',output/'target_collision.stl')
    root=ET.parse(package/'model.xml').getroot();world=root.find('worldbody')
    support=np.asarray(task['support_pose']);bounds=np.asarray(task['support_bounds_local_m']);dims=bounds[1]-bounds[0]
    sources=add_robot(root,output,support,dict(zip(('width','length','height'),dims)))
    ET.SubElement(world,'geom',name='robot_mount',type='box',pos='0 0 .01',size='.09 .09 .01',group='3',rgba='.2 .2 .2 1')
    ET.ElementTree(root).write(output/'model_unmounted.xml',encoding='unicode')
    model=mujoco.MjModel.from_xml_path(str(output/'model_unmounted.xml'));data=mujoco.MjData(model);ctrl=PandaController(model,data)
    owner=owners(model);contacts=ContactPolicy(model,owner,task);bid=model.body('base').id;mount=model.geom('robot_mount').id
    target_id=model.body(task['target_body']).id;qi=int(model.jnt_qposadr[model.body_jntadr[target_id]])
    finger_qi=[int(model.jnt_qposadr[model.joint(n).id]) for n in ['finger_joint1','finger_joint2']]
    start=np.asarray(task['start_pose_z_up']);goal=np.asarray(task['goal_pose_z_up']);width=task['target_dimensions_m'][0]
    require(width+.01<=.08,'gripper_width')
    grasp_offset=np.array([0.,0.,task['target_dimensions_m'][2]/2-limits['grasp_offset_from_top_m']])
    grip_start=matrix(start[:3,3]+start[:3,:3]@grasp_offset,start[:3,:3]@np.diag([1.,-1.,-1.]))
    held=np.linalg.inv(grip_start)@start
    pregrasp=grip_start.copy();pregrasp[2,3]+=.10
    lifted=start.copy();lifted[2,3]+=limits['lift_m'];grip_lift=lifted@np.linalg.inv(held)
    reoriented=goal.copy();reoriented[2,3]=max(start[2,3],goal[2,3])+limits['lift_m'];grip_rotate=reoriented@np.linalg.inv(held)
    release=goal.copy();release[2,3]+=limits['release_clearance_m'];grip_release=release@np.linalg.inv(held)
    retreat=grip_release.copy();retreat[2,3]+=.10
    stages=[('pregrasp',pregrasp,False,False),('grasp',grip_start,False,True),('lift',grip_lift,True,True),
        ('reorient',grip_rotate,True,True),('release',grip_release,True,True),('retreat',retreat,False,False)]
    # Same eight support-relative mount candidates as the existing bridge, frozen here.
    full_dims=dims.copy()
    full_dims[:2]+=2*protocol['selection']['surface_edge_inset_m'];w,l=full_dims[:2]
    offsets=[(-w/2+.11,0),(w/2-.11,0),(-w/2+.11,-l/4),(w/2-.11,-l/4),
        (-w/4,-l/2+.11),(w/4,-l/2+.11),(-w/4,l/2-.11),(w/4,l/2-.11)]
    local=read(config/'local_contact/task.json');top=support[2,3]+local['maximum_support_height_local_m']
    candidates=[];selected=None
    for index,(x,y) in enumerate(offsets[:limits['maximum_mount_candidates']]):
        began=time.monotonic();xyz=support[:3,3]+support[:3,:3]@np.array([x,y,0.]);xyz[2]=top+.02
        direction=support[:3,3]-xyz;yaw=np.arctan2(direction[1],direction[0]);basequat=[np.cos(yaw/2),0,0,np.sin(yaw/2)]
        model.body_pos[bid]=xyz;model.body_quat[bid]=basequat;model.geom_pos[mount]=xyz-[0,0,.01]
        mujoco.mj_resetData(model,data);data.qpos[ctrl.qi]=ctrl.qhome;data.qpos[finger_qi]=[.04,-.04];set_target(data,qi,start);mujoco.mj_forward(model,data)
        row=dict(index=index,mount_position=xyz.tolist(),mount_quaternion=basequat,stages=[],status='checking')
        candidates.append(row)
        try:
            home_bad=contacts.violations(data,limits['max_static_penetration_m'],allow_fingers=False,allow_support=True)
            row['home_violations']=home_bad;require(not home_bad,'home_collision')
            # Probe only generated support; robot fixture excluded from the ray group.
            group=np.array([0,0,0,1,0,0],dtype=np.uint8);saved_group=model.geom_group[mount];model.geom_group[mount]=0
            mount_rays=[]
            try:
                for dx,dy in [(0,0),(-.09,-.09),(-.09,.09),(.09,-.09),(.09,.09)]:
                    corner=xyz+support[:3,:3]@np.array([dx,dy,0.]);corner[2]=top+.3;gid=np.array([-1],dtype=np.int32)
                    distance=mujoco.mj_ray(model,data,corner,np.array([0.,0.,-1.]),group,1,target_id,gid)
                    ok=distance>=0 and owner.get(int(gid[0]))==task['support_body'] and abs(corner[2]-distance-top)<=.015
                    mount_rays.append(dict(distance=float(distance),geom=int(gid[0]),passed=bool(ok)))
                row['mount_rays']=mount_rays;require(all(r['passed'] for r in mount_rays),'mount_not_supported')
            finally:model.geom_group[mount]=saved_group
            q=ctrl.qhome.copy()
            for name,wanted,is_held,allow_fingers in stages:
                ctrl.target_rot=wanted[:3,:3];solution,residual=ctrl.ik(wanted[:3,3],q)
                data.qpos[ctrl.qi]=solution;mujoco.mj_kinematics(model,data)
                actual=matrix(data.site_xpos[ctrl.site].copy(),data.site_xmat[ctrl.site].reshape(3,3).copy())
                poserr=float(np.linalg.norm(actual[:3,3]-wanted[:3,3]));roterr=float(np.rad2deg(Rotation.from_matrix(wanted[:3,:3]@actual[:3,:3].T).magnitude()))
                record=dict(phase=name,position_error_m=poserr,orientation_error_deg=roterr,ik_residual=residual,q=solution.tolist(),gripper_pose=wanted.tolist(),held=is_held)
                row['stages'].append(record)
                require(poserr<=limits['ik_position_tolerance_m'] and roterr<=limits['ik_orientation_tolerance_deg'],'endpoint_ik:'+name)
                count=max(1,int(np.ceil(max(abs(solution-q))/limits['dense_joint_step_rad'])));bad=[]
                for k in range(count+1):
                    data.qpos[ctrl.qi]=q+(solution-q)*k/count
                    gap=width/2 if is_held else .04;data.qpos[finger_qi]=[gap,-gap]
                    mujoco.mj_kinematics(model,data)
                    target_pose=matrix(data.site_xpos[ctrl.site].copy(),data.site_xmat[ctrl.site].reshape(3,3).copy())@held if is_held else goal if name=='retreat' else start
                    set_target(data,qi,target_pose);mujoco.mj_forward(model,data)
                    bad=contacts.violations(data,limits['max_static_penetration_m'],allow_fingers=allow_fingers,allow_support=(not is_held or name=='lift'))
                    if bad:break
                record.update(dense_states_checked=k+1,planned_dense_states=count+1,violations=bad)
                require(not bad,'path_collision:'+name);q=solution
            row['status']='fixed_path_preflight_passed';selected=index
            set_pose(world.find("body[@name='base']"),matrix(xyz,Rotation.from_quat(np.array(basequat)[[1,2,3,0]]).as_matrix()))
            world.find("geom[@name='robot_mount']").set('pos',vec(xyz-[0,0,.01]))
            ET.ElementTree(root).write(output/'model.xml',encoding='unicode');break
        except ValueError as exc:row.update(status='preflight_rejected',reason=str(exc))
        finally:row['elapsed_seconds']=time.monotonic()-began
    result=dict(passed=selected is not None,status='preflight_passed' if selected is not None else 'fixed_robot_preflight_not_passed',
        selected_index=selected,candidates=candidates,held_transform=held.tolist(),start_grip_pose=grip_start.tolist(),
        release_object_pose=release.tolist(),robot_sources=sources,new_physics_steps=0,
        interpretation='finite kinematic checks only; no successful grasp or task dynamics inferred')
    write_new(output/'PREFLIGHT.json',result)
    write_new(output/'task.json',dict(task,robot_preflight=result,robot='Panda',original_robot_parameters_preserved=True))
    if selected is not None:
        native=mujoco.MjModel.from_xml_path(str(output/'model.xml'));mujoco.mj_saveModel(native,str(output/'model.mjb'),None)
    write_new(output/'FILES.json',{str(p.relative_to(output)):reference(p) for p in sorted(output.rglob('*')) if p.is_file()})
    return result
