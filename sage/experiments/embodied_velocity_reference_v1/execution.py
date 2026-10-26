"""One actuator episode and one independent control replay per eligible request."""
from pathlib import Path
import traceback
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import read,require,write_new,reference,digest
from sage.experiments.embodied_scene_bridge.environment import owners
from sage.experiments.embodied_planner_m2_v2.contacts import ContactPolicy
from .controller import VelocityReferenceController,cubic_step
from sage.experiments.embodied_task_scene_v1.robot import matrix
from .entry import load


def contacts(model,data):
    import mujoco
    rows=[]
    for index,c in enumerate(data.contact):
        force=np.zeros(6);mujoco.mj_contactForce(model,data,index,force)
        rows.append(np.r_[c.geom1,c.geom2,c.dist,c.pos,c.frame,force])
    return np.array(rows,dtype=np.float64).reshape(-1,21)


def episode(config,protocol_path,output):
    import mujoco
    config=Path(config);output=Path(output);output.mkdir(exist_ok=False);protocol=read(protocol_path);limits=protocol['execution']
    require(str(config)==protocol['source_config'],'source_config_changed')
    binding=Path(protocol_path).parent.parent/'BINDING.json';model,_=load(binding,digest(binding),'controller_evaluation',protocol['request_id'])
    task=read(config/'package/task.json');plan=read(config/'package/PREFLIGHT.json')['selected'];goal=np.asarray(task['goal_pose_z_up'])
    data=mujoco.MjData(model);ctrl=VelocityReferenceController(model,data);policy=ContactPolicy(model,owners(model),task)
    require(abs(model.opt.timestep-limits['dt_s'])<1e-12,'time_step_mismatch')
    bid=model.body(task['target_body']).id;qi=int(model.jnt_qposadr[model.body_jntadr[bid]]);vi=int(model.jnt_dofadr[model.body_jntadr[bid]])
    fi=[model.jnt_qposadr[model.joint(n).id] for n in ['finger_joint1','finger_joint2']]
    data.qpos[ctrl.qi]=ctrl.qhome;data.qpos[fi]=[.04,-.04];mujoco.mj_forward(model,data)
    # All object state writes end with initialization; subsequent movement is actuated physics.
    initial_z=float(data.qpos[qi+2]);spec=int(mujoco.mjtState.mjSTATE_INTEGRATION);states=[];steps_at=[];allcontacts=[];offsets=[0];controls=[];phase_ids=[]
    events=[];metrics=[];joint_records=[];reference_positions=[];reference_velocities=[];unclipped=[];object_poses=[];phase_results=[];max_lift=0.;max_pen=0.;bilateral=best_bilateral=0;physical_steps=0;result=dict(status='running',success=False)
    def snapshot():
        state=np.empty(mujoco.mj_stateSize(model,spec));mujoco.mj_getState(model,data,state,spec);states.append(state);steps_at.append(physical_steps)
        c=contacts(model,data);allcontacts.append(c);offsets.append(offsets[-1]+len(c))
    snapshot()
    with np.load(protocol['baseline_raw']['path'],allow_pickle=False) as baseline:
        require(np.array_equal(states[0],baseline['states'][0]),'initial_full_state_changed')
    write_new(output/'STARTED.json',dict(request_id=protocol['request_id'],source_request=config.name,new_physical_attempts=1,initial_full_state_exact_baseline=True))
    last_q=ctrl.qhome.copy();last_grip=.04;held=np.asarray(plan['held_transform'])
    phases=[*plan['endpoints'],dict(phase='settle',q=plan['endpoints'][-1]['q'])]
    try:
        for phase_index,point in enumerate(phases):
            phase=point['phase'];q=np.asarray(point['q']);grip=.04 if phase in ['pregrasp','grasp','open','retreat','settle'] else 0.
            count=int(round(limits['phase_durations'][phase]/limits['dt_s']));events.append(dict(phase=phase,start_step=physical_steps))
            if phase=='open':
                require(data.qpos[qi+2]-goal[2,3]<=limits['max_release_gap_m'],'actual_release_gap_exceeds_task')
                require(np.rad2deg(Rotation.from_matrix(goal[:3,:3].T@data.xmat[bid].reshape(3,3)).magnitude())<=limits['goal_orientation_deg'],'actual_release_orientation')
            for k in range(1,count+1):
                require(physical_steps<limits['max_steps_per_episode'],'episode_step_budget')
                t=k/count;a=t*t*(3-2*t);qref,vref=cubic_step(last_q,q,k,count,limits['dt_s'])
                force=ctrl.action(qref,last_grip+(grip-last_grip)*a,vref)
                reference_positions.append(qref);reference_velocities.append(vref);unclipped.append(force)
                controls.append(data.ctrl.copy());phase_ids.append(phase_index);mujoco.mj_step(model,data);physical_steps+=1;mujoco.mj_forward(model,data)
                joint_records.append(np.r_[data.qpos[ctrl.qi],data.qvel[ctrl.vi]]);object_poses.append(data.qpos[qi:qi+7].copy())
                cc=contacts(model,data);support_z=0.;f1=f2=False;target_pen=0.
                for c in cc:
                    g1,g2=int(c[0]),int(c[1]);pair={g1,g2}
                    if pair&policy.target:
                        target_pen=max(target_pen,-c[2])
                        f1|=bool(pair&{model.geom('finger1_collision').id,model.geom('finger1_pad_collision').id} and c[15]>.01)
                        f2|=bool(pair&{model.geom('finger2_collision').id,model.geom('finger2_pad_collision').id} and c[15]>.01)
                        if pair&policy.support:
                            worldforce=c[6:15].reshape(3,3).T@c[15:18];support_z+=(1 if g2 in policy.target else -1)*worldforce[2]
                bilateral=bilateral+1 if f1 and f2 else 0;best_bilateral=max(best_bilateral,bilateral)
                max_lift=max(max_lift,float(data.qpos[qi+2]-initial_z));max_pen=max(max_pen,target_pen)
                speed=float(np.linalg.norm(data.qvel[vi:vi+3]));angular=float(np.linalg.norm(data.qvel[vi+3:vi+6]));xy=float(np.linalg.norm(data.qpos[qi:qi+2]-goal[:2,3]))
                angle=float(np.rad2deg(Rotation.from_matrix(goal[:3,:3].T@data.xmat[bid].reshape(3,3)).magnitude()))
                metrics.append([data.time,speed,angular,xy,angle,support_z/(model.body_mass[bid]*9.81)])
                if physical_steps%10==0:snapshot()
                require(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all(),'nonfinite_physics')
                require(not any(w.number for w in data.warning),'simulator_warning')
                require(target_pen<=limits['max_penetration_m'],'target_penetration')
                bad=policy.violations(data,limits['max_penetration_m'],allow_fingers=phase not in ['pregrasp','retreat','settle'],allow_support=phase in ['pregrasp','grasp','close','lift','open','retreat','settle'])
                require(not bad,'forbidden_contact:'+str(bad[:3]))
                if phase in ['lift','transfer','release']:
                    expected=matrix(data.site_xpos[ctrl.site].copy(),data.site_xmat[ctrl.site].reshape(3,3))@held
                    require(np.linalg.norm(expected[:3,3]-data.qpos[qi:qi+3])<=limits['max_object_grasp_slip_m'],'grasp_slip')
            error=float(max(abs(data.qpos[ctrl.qi]-q)))
            phase_results.append(dict(phase=phase,end_step=physical_steps,maximum_joint_error_rad=error,maximum_joint_speed_rad_s=float(max(abs(data.qvel[ctrl.vi]))),tracking_passed=error<=limits['max_joint_tracking_error_rad']))
            require(error<=limits['max_joint_tracking_error_rad'],'joint_tracking:'+phase)
            if phase=='close':require(best_bilateral>=limits['min_bilateral_contact_steps'],'no_bilateral_grasp')
            if phase=='lift':require(max_lift>=limits['min_lift_m'],'insufficient_lift')
            last_q=q;last_grip=grip
        tail=np.asarray(metrics)[-int(limits['tail_s']/limits['dt_s']):]
        require(len(tail)==int(limits['tail_s']/limits['dt_s']),'missing_stability_tail')
        require(np.max(tail[:,1])<=limits['speed_m_s'] and np.max(tail[:,2])<=limits['angular_speed_rad_s'],'unstable_tail')
        require(np.max(tail[:,3])<=limits['goal_xy_m'] and np.max(tail[:,4])<=limits['goal_orientation_deg'],'goal_pose_error')
        ratio=float(tail[:,5].mean());require(limits['support_weight_ratio'][0]<=ratio<=limits['support_weight_ratio'][1],'support_load')
        result.update(status='fixed_episode_passed',success=True)
    except BaseException as exc:result.update(status='fixed_episode_failed',error=str(exc),traceback=traceback.format_exc())
    finally:
        if steps_at[-1]!=physical_steps:snapshot()
        raw=output/'RAW.npz';np.savez_compressed(raw,controls=np.asarray(controls).reshape(-1,model.nu),phase_ids=phase_ids,
            states=np.asarray(states),snapshot_steps=steps_at,contacts=np.concatenate(allcontacts),contact_offsets=offsets,metrics=np.asarray(metrics).reshape(-1,6),
            joint_states=np.asarray(joint_records).reshape(-1,14),reference_positions=np.asarray(reference_positions).reshape(-1,7),
            reference_velocities=np.asarray(reference_velocities).reshape(-1,7),unclipped_forces=np.asarray(unclipped).reshape(-1,7),object_qpos=np.asarray(object_poses).reshape(-1,7))
        result.update(new_physical_attempts=1,new_physics_steps=physical_steps,maximum_lift_m=max_lift,maximum_target_penetration_m=max_pen,
            longest_bilateral_steps=best_bilateral,events=events,phase_results=phase_results,state_spec=spec,raw=reference(raw),binding=reference(binding),
            initial_full_state_exact_baseline=True,controller_change='analytical desired joint velocity only',
            object_pose_writes_after_initialization=0,new_ik_queries=0,qualified_collection=False,qualified_export=False)
        write_new(output/'RESULT.json',result)
    return result


def replay(config,source,output):
    import mujoco
    config=Path(config);source=Path(source);output=Path(output);output.mkdir(exist_ok=False)
    write_new(output/'STARTED.json',dict(request_id=config.name,new_physical_attempts=1,kind='independent_saved_control_replay'))
    result=read(source/'RESULT.json');binding=Path(result['binding']['path']);protocol=read(read(binding)['protocol']['path'])
    model,_=load(binding,result['binding']['sha256'],'controller_evaluation',protocol['request_id'])
    data=mujoco.MjData(model);raw=np.load(source/'RAW.npz',allow_pickle=False);spec=result['state_spec']
    require(reference(source/'RAW.npz')==result['raw'],'replay_raw_changed')
    mujoco.mj_setState(model,data,raw['states'][0],spec);mujoco.mj_forward(model,data);mujoco.mj_setState(model,data,raw['states'][0],spec)
    lookup={int(n):i for i,n in enumerate(raw['snapshot_steps'])};state_error=contact_error=0.;steps=0;status='replay_passed';error=None
    try:
        for step,control in enumerate(raw['controls'],1):
            data.ctrl[:]=control;mujoco.mj_step(model,data);steps+=1;mujoco.mj_forward(model,data)
            if step in lookup:
                i=lookup[step];state=np.empty(len(raw['states'][i]));mujoco.mj_getState(model,data,state,spec)
                state_error=max(state_error,float(np.max(abs(state-raw['states'][i]))))
                actual=contacts(model,data);expected=raw['contacts'][raw['contact_offsets'][i]:raw['contact_offsets'][i+1]]
                require(actual.shape==expected.shape,'contact_count_replay');contact_error=max(contact_error,float(np.max(abs(actual-expected),initial=0)))
        require(state_error<=1e-12 and contact_error<=1e-12,'state_or_contact_replay_error')
    except BaseException as exc:status='replay_failed';error=str(exc)
    value=dict(status=status,passed=status=='replay_passed',error=error,state_max_error=state_error,contact_max_error=contact_error,
        source=reference(source/'RESULT.json'),new_physical_attempts=1,new_physics_steps=steps,source_episode_success=result['success'],qualification_inferred=False)
    write_new(output/'RESULT.json',value);return value
