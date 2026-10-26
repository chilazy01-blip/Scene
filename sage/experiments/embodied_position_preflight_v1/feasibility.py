"""Endpoint and exact joint-path diagnostics, separated from physical execution."""
import mujoco,numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_bridge.environment import support_probe
from sage.experiments.embodied_container_m2.cavity import bottom_probe,containment
from sage.experiments.embodied_planner_m2_v2.planner import JointPlanner,PlanningFailure


def waypoints(task):
    start,goal=np.asarray(task['start']),np.asarray(task['goal'])
    height=task['grasp_height_offset_m']
    high=task['cavity']['highest_collision_z_world_m']+.03+task['target_dimensions_m'][2]/2
    return [('approach',start+[0,0,height+.12],start,.04,False),
            ('grasp',start+[0,0,height],start,.04,True),
            ('lift_clear',np.r_[start[:2],high+height],np.r_[start[:2],high],.019,True),
            ('transfer_clear',np.r_[goal[:2],high+height],np.r_[goal[:2],high],.019,True),
            ('entry_mid',goal+[0,0,height+.08],goal+[0,0,.08],.019,True),
            ('place',goal+[0,0,height+.004],goal+[0,0,.004],.019,True),
            ('release_open',goal+[0,0,height+.004],goal,.04,False),
            ('retreat_clear',np.r_[goal[:2],high+height],goal,.04,False)]


def put(env,q,object_position,grip):
    env.data.qpos[env.ctrl.qi]=q
    env.data.qpos[env.qi[-2:]]=[grip,-grip]
    env.data.qpos[env.target_qi:env.target_qi+3]=object_position
    env.data.qpos[env.target_qi+3:env.target_qi+7]=env.task['target_quat']
    mujoco.mj_forward(env.model,env.data)


def endpoints(env,spec,contract):
    t=env.task;q=env.ctrl.qhome.copy();start=np.asarray(t['start'])
    assert np.allclose(env.observe()['proprio'],contract['initial_proprio'],rtol=0,atol=1e-12)
    base=env.model.body('base').id
    assert np.allclose(env.model.body_pos[base],contract['robot_mount']['position_m'],rtol=0,atol=1e-12)
    assert np.allclose(env.model.body_quat[base],contract['robot_mount']['quaternion_wxyz'],rtol=0,atol=1e-12)
    for item in contract['cameras'].values():
        cam=env.model.camera(item['model_camera']);i=cam.id
        assert np.allclose(env.model.cam_pos[i],item['local_position_m'],rtol=0,atol=1e-12)
        assert np.allclose(env.model.cam_quat[i],item['local_quaternion_wxyz'],rtol=0,atol=1e-12)
        assert env.model.cam_fovy[i]==item['fovy_degrees']
    home=env.contact_policy.violations(env.data,.001,allow_fingers=False)
    mount_support=support_probe(env.model,env.data,t,np.asarray(contract['robot_mount']['position_m']),half_xy=[.09,.09])
    start_support=support_probe(env.model,env.data,t,start)
    bottom=bottom_probe(env.model,env.data,t)
    assert containment(t,np.asarray(t['goal']),t['target_quat'])['inside']
    rows=[]
    for phase,position,obj,grip,fingers in waypoints(t):
        q,error=env.ctrl.ik(position,q);put(env,q,obj,grip)
        bad=env.contact_policy.violations(env.data,.001,allow_fingers=fingers)
        rows.append(dict(phase=phase,position_m=position.tolist(),q=q.tolist(),residual=float(error),forbidden_contacts=bad))
    corners=[];height=t['grasp_height_offset_m'];high=waypoints(t)[2][2][2]
    for dx,dy in [(-.02,-.02),(-.02,.02),(.02,-.02),(.02,.02)]:
        obj=start+[dx,dy,0];q=env.ctrl.qhome.copy();put(env,q,obj,.04)
        support=support_probe(env.model,env.data,t,obj)
        for phase,position,object_position in [('approach',obj+[0,0,height+.12],obj),('grasp',obj+[0,0,height],obj),('lift_clear',np.r_[obj[:2],high+height],np.r_[obj[:2],high])]:
            q,error=env.ctrl.ik(position,q);put(env,q,object_position,.04)
            bad=env.contact_policy.violations(env.data,.001,allow_fingers=phase!='approach')
            corners.append(dict(phase=phase,jitter_xy=[dx,dy],q=q.tolist(),residual=float(error),forbidden_contacts=bad,support_passed=bool(support)))
    passed=not home and all(x['residual']<spec['endpoint_residual_m_max'] and not x['forbidden_contacts'] for x in rows+corners)
    return dict(passed=passed,home_collisions=home,mount_support=mount_support,start_support=start_support,bottom_probe=bottom,nominal=rows,corners=corners,new_physics_steps=0,diagnostic_pose_writes=True,configuration_specific_mount_changes=0)


def paths(env,spec,seed,endpoint_result):
    env.reset(seed,jitter=False);planner=JointPlanner(env,spec['planner'],seed)
    rows=[];motion_seconds=0.;current_object=np.asarray(env.task['start']).copy()
    try:
        for point,solved in zip(waypoints(env.task),endpoint_result['nominal']):
            phase,position,obj,grip,fingers=point
            held=phase in ['lift_clear','transfer_clear','entry_mid','place']
            if phase=='release_open':
                put(env,env.data.qpos[env.ctrl.qi].copy(),obj,grip);current_object=obj.copy()
            attachment=np.linalg.inv(env.grip_pose())@env.target_pose() if held else None
            path=planner.plan(np.asarray(solved['q']),phase,grip,attachment,allow_fingers=fingers,allow_support=phase in ['lift_clear','place'])
            for first,last in zip(path[:-1],path[1:]):
                distance=float(max(abs(last-first)));duration=max(.10,1.5*distance/.5,np.sqrt(6*distance/1.))
                motion_seconds+=max(2,int(np.ceil(duration/.05)))*.05
            env.data.qpos[env.ctrl.qi]=path[-1];env.data.qpos[env.qi[-2:]]=[grip,-grip];mujoco.mj_forward(env.model,env.data)
            if attachment is not None:
                predicted=env.grip_pose()@attachment;current_object=predicted[:3,3].copy()
                env.data.qpos[env.target_qi:env.target_qi+3]=current_object
                env.data.qpos[env.target_qi+3:env.target_qi+7]=Rotation.from_matrix(predicted[:3,:3]).as_quat()[[3,0,1,2]]
                mujoco.mj_forward(env.model,env.data)
            rows.append(dict(phase=phase,waypoints=len(path)))
        return dict(passed=True,records=planner.records,estimated_motion_seconds=motion_seconds,new_physics_steps=0,nominal_only=True,ideal_grasp_attachment=True,physical_task_success_proven=False)
    except PlanningFailure as exc:
        return dict(passed=False,reason=str(exc),records=planner.records,estimated_motion_seconds=motion_seconds,new_physics_steps=0,nominal_only=True,physical_task_success_proven=False)
