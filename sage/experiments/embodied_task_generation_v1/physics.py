"""Frozen pose-aware release cases; no search, training, or robot integration."""
from pathlib import Path
import time, traceback
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_scene_quality_v2.contracts import require,write_new,read,reference,fingerprint
from sage.experiments.embodied_scene_quality_v2.primitives import get_state,contact_rows
from .planner import corners


def quat(rotation):
    return rotation.as_quat()[[3,0,1,2]]


def rotation(q):
    return Rotation.from_quat(np.asarray(q)[...,[1,2,3,0]])


def description(model,task):
    import mujoco
    require(model.nq==7 and model.nv==6 and model.nu==0,'isolated_model_layout')
    target=model.body(task['target_body']).id
    return dict(target_geom_ids=[model.geom('target_collision').id],
        bottom_geom_ids=[model.geom(n).id for n in task['contact_names']],wall_geom_ids=[],desk_geom_ids=[],
        target_body_id=target,state_spec=task['state_spec'],state_size=task['state_size'],
        mass_kg=float(model.body_mass[target]),inertia=model.body_inertia[target].tolist(),
        timestep_s=float(model.opt.timestep),mujoco_version=mujoco.__version__)


def freeze_initials(model,task,protocol):
    import mujoco
    desc=description(model,task);support=np.asarray(task['support_pose']);nominal=rotation(task['nominal_quaternion_wxyz'])
    support_r=Rotation.from_matrix(support[:3,:3]);hull=np.asarray(task['target_hull_vertices']);result={}
    for case in protocol['cases']:
        local_delta=Rotation.from_euler('xyz',case['euler_xyz_local_deg'],degrees=True)
        orient=support_r*local_delta*support_r.inv()*nominal
        local_vertices=(hull@orient.as_matrix().T)@support[:3,:3]
        local_position=np.r_[case['offset_xy_local_m'],task['maximum_support_height_local_m']-local_vertices[:,2].min()+case['clearance_m']]
        data=mujoco.MjData(model);data.qpos[:3]=support[:3,3]+support[:3,:3]@local_position;data.qpos[3:]=quat(orient)
        velocity=np.asarray(case['velocity_local_m_s_rad_s']);linear=support[:3,:3]@velocity[:3];angular=support[:3,:3]@velocity[3:]
        # Native differentiation handles the free joint's angular-velocity convention.
        epsilon=1e-6;nextq=data.qpos.copy();nextq[:3]+=epsilon*linear
        nextq[3:]=quat(Rotation.from_rotvec(epsilon*angular)*orient)
        mujoco.mj_differentiatePos(model,data.qvel,epsilon,data.qpos,nextq)
        mujoco.mj_forward(model,data)
        penetration=max([0.]+[-float(c.dist) for c in data.contact])
        require(penetration<=protocol['physics']['initial_penetration_m_max'],'initial_overlap:'+case['key'])
        result[case['key']]=dict(complete_state=get_state(model,data,desc).tolist(),qpos=data.qpos.tolist(),qvel=data.qvel.tolist(),penetration_m=penetration)
    return dict(cases=result,description=desc,protocol_sha256=fingerprint(protocol),new_physics_steps=0)


def run_attempt(directory,model,task,case,initial,protocol,binding_sha,purpose):
    import mujoco
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    desc=description(model,task);dt=float(model.opt.timestep);steps=round(protocol['physics']['duration_s']/dt)
    record=dict(case=case['key'],purpose=purpose,binding_sha256=binding_sha,dt_s=dt,maximum_steps=steps,
        initial_sha256=fingerprint(initial),started_at=time.time(),status='started',new_physics_steps=0,description=desc)
    write_new(directory/'STARTED.json',record);write_new(directory/'INITIAL.json',initial)
    started=time.monotonic();data=mujoco.MjData(model)
    state=np.asarray(initial['complete_state']);mujoco.mj_setState(model,data,state,desc['state_spec'])
    mujoco.mj_forward(model,data);penetration=max([0.]+[-float(c.dist) for c in data.contact])
    mujoco.mj_setState(model,data,state,desc['state_spec'])
    positions=[];velocities=[];states=[get_state(model,data,desc)];times=[];contacts=[];frames=[];error=None
    try:
        require(penetration<=protocol['physics']['initial_penetration_m_max'],'initial_penetration')
        for step in range(steps):
            mujoco.mj_step(model,data);record['new_physics_steps']+=1
            times.append(float(data.time));positions.append(data.qpos.copy());velocities.append(data.qvel.copy());states.append(get_state(model,data,desc))
            rows=contact_rows(model,data,desc,step);contacts.extend(rows)
            targets=set(desc['target_geom_ids'])
            frames.extend(c.frame.copy() for c in data.contact if (int(c.geom1) in targets)!=(int(c.geom2) in targets))
            require(np.isfinite(states[-1]).all(),'nonfinite_native_state')
            require(not any(w.number for w in data.warning),'native_warning')
            if max([0.]+[-r[4] for r in rows])>protocol['physics']['max_target_penetration_m']:
                record['status']='physical_engineering_rejection:penetration';break
        else:record['status']='completed'
    except BaseException as exc:
        record.update(status='engineering_error',error=repr(exc),traceback=traceback.format_exc());error=exc
    finally:
        np.savez_compressed(directory/'RAW.npz',time=np.asarray(times),qpos=np.asarray(positions).reshape(-1,7),
            qvel=np.asarray(velocities).reshape(-1,6),full_state=np.asarray(states),contacts=np.asarray(contacts).reshape(-1,15),
            contact_frames=np.asarray(frames).reshape(-1,9),warnings=np.array([w.number for w in data.warning]))
        record.update(raw=reference(directory/'RAW.npz'),initial=reference(directory/'INITIAL.json'),
            elapsed_seconds=time.monotonic()-started,finished_at=time.time(),
            force_state_timing='native solver contacts; qpos/qvel after integration; all nine contact-frame components retained')
        write_new(directory/'ATTEMPT.json',record)
    if error:raise error
    return record


def evaluate(raw,initial,attempt,task,protocol):
    """Recompute all conditions from raw arrays; the summary pass flag is unused."""
    q=raw['qpos'];v=raw['qvel'];n=len(q);dt=attempt['dt_s'];p=protocol['physics'];states=raw['full_state'];c=raw['contacts'];frames=raw['contact_frames']
    require(n==attempt['new_physics_steps'] and q.shape==(n,7) and v.shape==(n,6),'trace_shape')
    require(states.shape==(n+1,task['state_size']) and c.shape[1:]==(15,) and frames.shape==(len(c),9),'state_contact_shape')
    require(all(np.isfinite(raw[k]).all() for k in raw),'nonfinite_raw')
    require(np.array_equal(states[0],np.asarray(initial['complete_state'])),'initial_state_mismatch')
    require(np.allclose(states[1:,1:8],q,rtol=0,atol=1e-12) and np.allclose(states[1:,8:14],v,rtol=0,atol=1e-12),'state_slice_mismatch')
    require(np.allclose(raw['time'],np.arange(1,n+1)*dt,rtol=0,atol=1e-10),'time_mismatch')
    require(np.allclose(states[1:,0],raw['time'],rtol=0,atol=1e-12),'state_time_mismatch')
    desc=attempt['description'];targets=set(desc['target_geom_ids']);supports=set(desc['bottom_geom_ids'])
    if len(c):
        require(np.all(c[:,0]==c[:,0].astype(int)) and c[:,0].min()>=0 and c[:,0].max()<n,'contact_step')
        require(all(((int(r[1]) in targets) and (int(r[2]) in supports)) or ((int(r[2]) in targets) and (int(r[1]) in supports)) for r in c),'contact_identity')
        require(np.all(c[:,3]==0),'unsupported_contact_kind')
        signs=np.array([-1 if int(r[1]) in targets else 1 for r in c])
        require(np.allclose(c[:,8],frames[:,2]*signs,rtol=0,atol=1e-12),'contact_frame_sign')
        fm=frames.reshape(-1,3,3)
        require(np.allclose(fm@fm.transpose(0,2,1),np.eye(3),atol=1e-8,rtol=0),'contact_frame_orthonormal')
    complete=attempt['status']=='completed' and n==round(p['duration_s']/dt) and not raw['warnings'].any()
    maximum_penetration=max([initial['penetration_m'],0.]+(-c[:,4]).tolist())
    if not n:return dict(passed=False,complete=False,reason='no_integrated_steps',maximum_penetration_m=maximum_penetration)
    require(np.allclose(np.linalg.norm(q[:,3:],axis=1),1,atol=1e-8,rtol=0),'quaternion_norm')
    tail=raw['time']>=p['duration_s']-p['stable_tail_s']-1e-10
    if not tail.any():tail[-1]=True
    rotations=rotation(q[:,3:]);nominal=rotation(task['nominal_quaternion_wxyz'])
    angle=np.rad2deg((rotations*nominal.inv()).magnitude());speed=np.linalg.norm(v[:,:3],axis=1);omega=np.linalg.norm(v[:,3:],axis=1)
    xy_drift=np.linalg.norm(q[:,:2]-np.asarray(initial['qpos'])[:2],axis=1);goal_error=np.linalg.norm(q[:,:2]-np.asarray(task['goal'])[:2],axis=1)
    world_points=np.einsum('nij,kj->nki',rotations.as_matrix(),corners(task['target_dimensions_m']))+q[:,:3,None].transpose(0,2,1)
    support=np.asarray(task['support_pose']);local=(world_points-support[:3,3])@support[:3,:3]
    roi=np.asarray(task['roi_xy_m']);bounds=np.asarray(task['support_bounds_local_m'])
    lower=np.maximum(roi[0],bounds[0,:2]);upper=np.minimum(roi[1],bounds[1,:2])
    margin=np.minimum(local[:,:,:2]-lower,upper-local[:,:,:2]).min(axis=(1,2))
    force=np.zeros(n)
    if len(c):np.add.at(force,c[:,0].astype(int),c[:,8]*c[:,9])
    weight=task['physical_prior']['mass_kg']*9.81;ratio=float(force[tail].mean()/weight)
    conditions=dict(complete=complete,initial_penetration=initial['penetration_m']<=p['initial_penetration_m_max'],
        penetration=maximum_penetration<=p['max_target_penetration_m'],
        speed=bool(np.max(speed[tail])<p['max_speed_m_s']),angular_speed=bool(np.max(omega[tail])<p['max_angular_speed_rad_s']),
        orientation=bool(np.max(angle[tail])<=p['orientation_error_deg_max']),xy_drift=bool(np.max(xy_drift[tail])<=p['xy_drift_m_max']),
        goal=bool(np.max(goal_error[tail])<p['goal_xy_tolerance_m']),containment=bool(np.min(margin[tail])>=p['containment_margin_m']),
        positive_support=bool(np.all(force[tail]>0)),mean_support=p['mean_support_weight_ratio'][0]<=ratio<=p['mean_support_weight_ratio'][1])
    return dict(passed=all(conditions.values()),complete=complete,conditions=conditions,
        maximum_penetration_m=maximum_penetration,tail_max_speed_m_s=float(max(speed[tail])),
        tail_max_angular_speed_rad_s=float(max(omega[tail])),tail_max_orientation_error_deg=float(max(angle[tail])),
        tail_max_xy_drift_m=float(max(xy_drift[tail])),tail_max_goal_error_m=float(max(goal_error[tail])),
        tail_min_containment_margin_m=float(min(margin[tail])),mean_support_weight_ratio=ratio,
        first_contact_time_s=float(raw['time'][int(c[0,0])]) if len(c) else None)


def numerical_comparison(base,other,base_eval,other_eval,protocol,replay=False):
    limits=protocol['numerical']
    if replay:
        same_shapes=set(base)==set(other) and all(base[k].shape==other[k].shape for k in base)
        errors={k:float(np.max(abs(base[k]-other[k]))) if base[k].size else 0. for k in base} if same_shapes else {}
        passed=same_shapes and all(x<=limits['replay_atol'] for x in errors.values()) and base_eval['complete'] and other_eval['complete']
        return dict(passed=passed,same_shapes=same_shapes,max_abs_errors=errors)
    stride=round(protocol['physics']['base_dt_s']/protocol['physics']['refined_dt_s'])
    aligned=len(other['time'])==len(base['time'])*stride
    if not aligned:return dict(passed=False,reason='incomplete_or_unaligned_trajectories')
    q=base['qpos'];oq=other['qpos'][stride-1::stride];v=base['qvel'];ov=other['qvel'][stride-1::stride]
    position=float(np.max(np.linalg.norm(q[:,:3]-oq[:,:3],axis=1)))
    angle=float(np.max(np.rad2deg((rotation(q[:,3:])*rotation(oq[:,3:]).inv()).magnitude())))
    speed=float(np.max(np.linalg.norm(v[:,:3]-ov[:,:3],axis=1)))
    contact=abs(base_eval['first_contact_time_s']-other_eval['first_contact_time_s']) if base_eval['first_contact_time_s'] is not None and other_eval['first_contact_time_s'] is not None else None
    passed=base_eval['complete'] and other_eval['complete'] and base_eval['passed']==other_eval['passed'] and position<=limits['position_tolerance_m'] and angle<=limits['orientation_tolerance_deg'] and speed<=limits['speed_tolerance_m_s'] and contact is not None and contact<=limits['first_contact_tolerance_s']
    return dict(passed=passed,position_max_m=position,orientation_max_deg=angle,speed_max_m_s=speed,first_contact_difference_s=contact)
