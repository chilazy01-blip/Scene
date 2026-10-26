"""Content-based qualification; caller supplies explicit registration."""
from pathlib import Path
import h5py
import mujoco
import numpy as np


def inspect_episode(directory, env, protocol, record, registration):
    directory=Path(directory);reasons=[]
    def check(condition, reason):
        if not condition:reasons.append(reason)
    check(registration is not None, 'unregistered_episode')
    if registration is not None:check(record['seed']==registration['seed'], 'registered_seed_mismatch')
    check(record.get('status')=='success' and record.get('result',{}).get('success') is True, 'physical_execution_not_successful')
    with h5py.File(directory/'trajectory.h5') as h:
        check(h.attrs.get('schema') in ('M2-development-episode/v1','M2-episode/v2'),'unknown_schema')
        check(int(h.attrs['seed'])==record['seed'],'hdf_seed_mismatch')
        check(bool(h.attrs['success'])==(record.get('status')=='success'),'hdf_outcome_mismatch')
        if h.attrs['schema']=='M2-episode/v2':
            check(h.attrs['source_manifest_sha256']==protocol['source_files_sha256'],'hdf_source_binding_mismatch')
            check(h.attrs['protocol_sha256']==record.get('protocol_sha256'),'hdf_protocol_binding_mismatch')
        actions=h['action'][:];states=h['privileged/state'][:];obs=h['observation/proprio'][:]
        times=h['observation/time'][:];audit=h['privileged/audit_1khz'][:];contacts=h['privileged/contacts_1khz'][:]
        n=len(actions);mask=int(h.attrs['state_spec'])
        check(len(states)==len(obs)==len(times)==n+1 and len(h['privileged/phase'])==n,'transition_count')
        check(all(np.isfinite(x).all() for x in [actions,states,obs,times,audit,contacts]),'nonfinite_data')
        check(len(audit)==n*50,'incomplete_physical_action')
        check(n>0,'empty_trajectory')
        if 'attempted' in h:
            check(np.all(h['attempted/executed_substeps'][:]==50),'interrupted_action')
            check(all(x=='completed' for x in h['attempted/status'].asstr()[:]),'action_exception')
            check(h['terminal'].attrs['native_steps']==n*50,'terminal_step_count')
            check(np.array_equal(h['terminal/state'][:],states[-1]),'terminal_state_mismatch')
        if reasons and ('nonfinite_data' in reasons or 'transition_count' in reasons or not n):
            return dict(accepted=False,reasons=reasons)
        env.reset(record['seed'])
        check(np.array_equal(env.state(),states[0]),'initialization_seed_state_mismatch')
        check(np.allclose(times,np.arange(n+1)*.05,atol=1e-8,rtol=0),'observation_timing')
        check(np.allclose(audit[:,0],np.arange(1,len(audit)+1)*.001,atol=1e-8,rtol=0),'audit_timing')
        speeds=[];angular=[];positions=[];max_proprio=0.;initial_q=None
        for i,state in enumerate(states):
            mujoco.mj_setState(env.model,env.data,state,mask)
            if i==0:initial_q=env.data.qpos[env.ctrl.qi].copy()
            max_proprio=max(max_proprio,float(np.max(abs(env.observe()['proprio']-obs[i]))))
            positions.append(env.data.qpos[env.target_qi:env.target_qi+3].copy())
            speeds.append(float(np.linalg.norm(env.data.qvel[env.target_vi:env.target_vi+3])))
            angular.append(float(np.linalg.norm(env.data.qvel[env.target_vi+3:env.target_vi+6])))
        check(max_proprio==0,'proprio_state_mismatch')
        rates=np.diff(np.vstack([initial_q,actions[:,:7]]),axis=0)/.05
        accel=np.diff(np.vstack([np.zeros(7),rates]),axis=0)/.05
        max_rate=float(abs(rates).max());max_acc=float(abs(accel).max())
        check(max_rate<=protocol['execution']['max_joint_target_rate_rad_s']+1e-8,'command_rate')
        check(max_acc<=protocol['execution']['max_joint_acceleration_rad_s2']+1e-8,'command_acceleration')
        bounds=env.model.jnt_range[env.ctrl.joints]
        check(bool(np.all(actions[:,:7]>=bounds[:,0]) and np.all(actions[:,:7]<=bounds[:,1])
                   and np.all((actions[:,7]>=0)&(actions[:,7]<=.04))),'action_bounds')
        bad=[]
        for row in contacts:
            a,b=int(row[2]),int(row[3])
            if not (0<=a<env.model.ngeom and 0<=b<env.model.ngeom):
                reasons.append('invalid_geom_id');break
            if row[4]<-protocol['success']['max_forbidden_penetration_m'] and not env.contact_policy.allowed(a,b):
                bad.append(dict(time_s=float(row[0]),geom1=a,geom2=b,penetration_m=-float(row[4])))
        check(not bad,'forbidden_contact')
        cfg=protocol['success'];positions=np.asarray(positions);goal=np.asarray(env.task['goal'])
        lift=float(max(audit[:,3])-positions[0,2]);goal_error=float(np.linalg.norm(positions[-1,:2]-goal[:2]))
        streak=maximum=0
        for value in np.minimum(audit[:,4],audit[:,5])>cfg['min_bilateral_force_n']:
            streak=streak+1 if value else 0;maximum=max(maximum,streak)
        check(lift>=cfg['min_lift_m'],'insufficient_lift')
        check(maximum*.001>=cfg['min_bilateral_s'],'insufficient_bilateral_contact')
        check(goal_error<cfg['goal_xy_tolerance_m'],'goal_error')
        check(audit[-1,9]>=cfg['stable_s'],'insufficient_stability')
        tail=max(1,int(round(cfg['stable_s']/.05)))
        check(max(speeds[-tail:])<cfg['max_speed_m_s'] and max(angular[-tail:])<cfg['max_angular_speed_rad_s'],'final_stability_velocity')
        last=audit[-int(round(cfg['stable_s']/.001)):]
        check(np.all(last[:,6]>0) and np.all(last[:,7]==0) and np.all(last[:,8]<cfg['goal_xy_tolerance_m']),'final_stability_contact')
        check(np.array_equal(positions[-1],audit[-1,1:4]),'audit_terminal_pose')
        return dict(accepted=not reasons,reasons=sorted(set(reasons)),actions=n,observations=len(states),
            max_proprio_error=max_proprio,max_command_rate_rad_s=max_rate,max_command_acceleration_rad_s2=max_acc,
            max_lift_m=lift,goal_xy_error_m=goal_error,bilateral_continuous_s=maximum*.001,
            forbidden_contacts=bad,filename_used_for_qualification=False)
