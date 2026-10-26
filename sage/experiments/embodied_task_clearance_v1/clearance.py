"""Reconstruct frozen path samples and endpoints without IK or integration."""
from pathlib import Path
import numpy as np
import trimesh
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference
from sage.experiments.codex_trellis_scene_v2.p021_physics import _read_glb,_geometry
from sage.experiments.embodied_scene_bridge.environment import owners
from sage.experiments.embodied_planner_m2_v2.contacts import ContactPolicy
from sage.experiments.embodied_task_scene_v1.robot import matrix,set_target
from .geometry import closed_components,solid_intervals,box_intervals,compare,pack


def diagnose(protocol,output):
    import mujoco
    config=Path(protocol['config']);output=Path(output);output.mkdir(exist_ok=False)
    saved=read(config/'robot/PREFLIGHT.json');task=read(config/'package/task.json');limits=protocol['geometry']
    plan=read(config/'generator/layout_plan_final.json');glb=config/'package/scene_start.glb'
    doc,_=_read_glb(glb);ids={n.get('extras',{}).get('scene_object_id') for n in doc['nodes']}-{None}
    groups,_=_geometry(glb,dict(room=plan['room'],objects=[dict(id=i) for i in sorted(ids)]))
    source=trimesh.util.concatenate([trimesh.Trimesh(p['vertices'],p['faces'],process=False) for p in groups[task['roles']['support_id']]])
    components,topology=closed_components(source,limits['topology_merge_decimal_digits'],limits['max_source_components'])
    write_new(output/'SOURCE_TOPOLOGY.json',topology)
    model=mujoco.MjModel.from_xml_path(str(config/'robot/model_unmounted.xml'));data=mujoco.MjData(model)
    arm_qi=np.array([model.jnt_qposadr[model.joint('joint'+str(i)).id] for i in range(1,8)])
    finger_qi=[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]
    site=model.site('grip_site').id;bid=model.body('base').id;mount=model.geom('robot_mount').id
    target=model.body(task['target_body']).id;qi=int(model.jnt_qposadr[model.body_jntadr[target]])
    support=model.body(task['support_body']).id;policy=ContactPolicy(model,owners(model),task);held=np.asarray(saved['held_transform'])
    support_ids=[i for i in range(model.ngeom) if model.geom_bodyid[i]==support and (model.geom_contype[i] or model.geom_conaffinity[i])]
    require(all(model.geom_type[i]==mujoco.mjtGeom.mjGEOM_BOX for i in support_ids),'unsupported_support_proxy')
    state_spec=int(mujoco.mjtState.mjSTATE_INTEGRATION);result=[]
    for candidate in protocol['frozen_cases']['mount_indices']:
        row=next(r for r in saved['candidates'] if r['index']==candidate)
        release=next(s for s in row['stages'] if s['phase']=='release');previous=next(s for s in row['stages'] if s['phase']=='reorient')
        goal_q=np.asarray(release['q']);start_q=np.asarray(previous['q']);fraction=(release['dense_states_checked']-1)/(release['planned_dense_states']-1)
        for label,q in [('first_saved_release_collision',start_q+(goal_q-start_q)*fraction),('saved_release_endpoint',goal_q)]:
            directory=output/(str(candidate)+'_'+label);directory.mkdir();write_new(directory/'STARTED.json',dict(candidate=candidate,state=label,new_physics_steps=0))
            model.body_pos[bid]=row['mount_position'];model.body_quat[bid]=row['mount_quaternion'];model.geom_pos[mount]=np.asarray(row['mount_position'])-[0,0,.01]
            mujoco.mj_resetData(model,data);data.qpos[arm_qi]=q;data.qpos[finger_qi]=[task['target_dimensions_m'][0]/2,-task['target_dimensions_m'][0]/2]
            mujoco.mj_kinematics(model,data);pose=matrix(data.site_xpos[site].copy(),data.site_xmat[site].reshape(3,3).copy())@held
            set_target(data,qi,pose);mujoco.mj_forward(model,data)
            bad=policy.violations(data,.001,allow_fingers=True,allow_support=False)
            if label=='first_saved_release_collision':
                expected=sorted((tuple(r['geoms']),r['penetration_m']) for r in release['violations']);actual=sorted((tuple(r['geoms']),r['penetration_m']) for r in bad)
                require([r[0] for r in actual]==[r[0] for r in expected],'reconstructed_contact_id_mismatch')
                require(max(abs(a[1]-b[1]) for a,b in zip(actual,expected))<=limits['native_contact_reconstruction_tolerance_m'],'reconstructed_contact_depth_mismatch')
            state=np.empty(mujoco.mj_stateSize(model,state_spec));mujoco.mj_getState(model,data,state,state_spec)
            np.savez_compressed(directory/'STATE.npz',full_state=state,qpos=data.qpos.copy(),qvel=data.qvel.copy(),
                native_contact_pos=np.array([c.pos for c in data.contact]),native_contact_frame=np.array([c.frame for c in data.contact]))
            tools=[]
            for tool_name in protocol['frozen_cases']['tools']:
                gid=model.geom(tool_name).id;mid=int(model.geom_dataid[gid]);adr=int(model.mesh_vertadr[mid]);n=int(model.mesh_vertnum[mid])
                points=model.mesh_vert[adr:adr+n]@data.geom_xmat[gid].reshape(3,3).T+data.geom_xpos[gid]
                faceadr=int(model.mesh_faceadr[mid]);facecount=int(model.mesh_facenum[mid])
                rawmesh=trimesh.Trimesh(points,model.mesh_face[faceadr:faceadr+facecount],process=False)
                tool=trimesh.convex.convex_hull(points);require(tool.is_watertight,'tool_hull_not_closed')
                lo,hi=tool.bounds;inset=limits['xy_edge_inset_m'];nx,ny=limits['grid']
                xx,yy=np.meshgrid(np.linspace(lo[0]+inset,hi[0]-inset,nx),np.linspace(lo[1]+inset,hi[1]-inset,ny),indexing='ij')
                xy=np.c_[xx.ravel(),yy.ravel()];zstart=max(source.bounds[1,2],hi[2])+.05;tol=limits['intersection_merge_tolerance_m']
                src,sknown=solid_intervals(components,xy,zstart,tol);ti,tknown=solid_intervals([tool],xy,zstart,tol)
                proxy=box_intervals(data.geom_xpos[support_ids],model.geom_size[support_ids],data.geom_xmat[support_ids].reshape(-1,3,3),xy,tol)
                value,raw=compare(src,proxy,ti,sknown,tknown,topology['complete'],limits['minimum_witness_overlap_m'])
                saved_groups=model.geom_group.copy();model.geom_group[:]=0;model.geom_group[gid]=5;native_errors=[]
                # mj_ray intersects mesh triangles, not the convex collision hull.
                indices=np.linspace(0,len(xy)-1,limits['tool_native_ray_spot_checks'],dtype=int)
                hits,rayids,_=rawmesh.ray.intersects_location(np.c_[xy[indices],np.full(len(indices),zstart)],
                    np.tile([0.,0.,-1.],(len(indices),1)),multiple_hits=True)
                tops={}
                for index,z in zip(rayids,hits[:,2]):tops[int(index)]=max(tops.get(int(index),-np.inf),float(z))
                try:
                    for rayindex,index in enumerate(indices):
                        hit=np.array([-1],dtype=np.int32)
                        distance=mujoco.mj_ray(model,data,np.r_[xy[index],zstart],np.array([0.,0.,-1.]),np.array([0,0,0,0,0,1],dtype=np.uint8),1,-1,hit)
                        expected=tops.get(rayindex)
                        require((distance>=0)==(expected is not None),'tool_native_ray_coverage')
                        if expected is not None:native_errors.append(abs(zstart-distance-expected))
                finally:model.geom_group[:]=saved_groups
                require(max(native_errors,default=0)<=limits['native_ray_tolerance_m'],'tool_native_ray_height')
                for name,intervals in [('source',src),('proxy',proxy),('tool',ti)]:raw[name+'_intervals'],raw[name+'_counts']=pack(intervals,limits['max_intervals_per_ray'])
                raw['xy']=xy;raw['tool_vertices']=np.asarray(tool.vertices);raw['tool_faces']=np.asarray(tool.faces)
                rawpath=directory/(tool_name+'.npz');np.savez_compressed(rawpath,**raw)
                value.update(tool=tool_name,raw=reference(rawpath),native_ray_max_error_m=max(native_errors,default=0),
                    native_ray_scope='compiled triangle mesh frame; overlap uses the convex collision hull',
                    witness_point_examples=[[*xy[i].tolist(),float(raw['witness_intervals'][i].mean())] for i in np.flatnonzero(raw['witness_mask'])[:5]])
                tools.append(value)
            record=dict(candidate=candidate,state=label,interpolation_fraction=float(fraction) if label.startswith('first') else 1.,
                reconstructed_from_saved_joints=True,violations=bad,state_data=reference(directory/'STATE.npz'),tools=tools,
                source_interference_witnessed=any(t['source_witness_count']>0 for t in tools),new_physics_steps=0,new_ik_queries=0)
            write_new(directory/'RESULT.json',record);result.append(record)
            print(candidate,label,[(t['tool'],t['classification'],t['source_witness_count']) for t in tools],flush=True)
    return dict(states=result,source_topology=topology,new_physics_steps=0,new_ik_queries=0,new_path_queries=0,
        endpoint_source_interference_count=sum(r['source_interference_witnessed'] for r in result if r['state']=='saved_release_endpoint'),
        interpretation='positive overlap witnesses involve source support solids and the existing convex tool collider; no witness never proves global clearance or real hardware feasibility')
