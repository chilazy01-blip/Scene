"""One continuous attempt: only ctrl writes after initialization; fail closed."""
from pathlib import Path
import gzip
import json
import numpy as np
import mujoco
from .native import Stretch, action
from .quality import relative_pose, pose_drift, contact_quality, contact_gate, TaskGate
from .build import write


def phases(config, selected):
    home, raised, extended, opened = [action(np.asarray(v)) for v in selected['waypoints']]
    close = opened.copy(); close[5] = 0.
    test = close.copy(); test[2] += .03
    lifted = close.copy(); lifted[2] += .10
    moved = lifted.copy(); moved[3] += selected['transport_extension_delta_m']
    placed = moved.copy(); placed[2] = close[2]
    released = placed.copy(); released[5] = config['planning']['full_open']
    retreat = released.copy(); retreat[2] += .08
    targets = [home, raised, extended, opened, close, test, test, lifted, moved, placed, released, retreat, retreat]
    rows = []; previous = targets[0]
    for (name, seconds), target in zip(config['phase_seconds'], targets):
        rows.append(dict(id=name, seconds=seconds, steps=round(seconds/config['control']['dt']),
                         initial=previous.tolist(), target=target.tolist(), ramp_seconds=seconds*2/3,
                         allow_hand=name not in ('hold','raise','extend','lower')))
        previous = target
    return rows


def target_at(phase, step, dt):
    u = np.clip(step*dt/phase['ramp_seconds'], 0, 1)
    s = u**3*(10-15*u+6*u*u)
    return np.array(phase['initial']) + s*(np.array(phase['target'])-phase['initial'])


def run(config, task, binding, selected, output):
    output = Path(output)
    (output/'PHYSICAL_ATTEMPT').open('x').close()
    control=config['control'];limits=control['limits'];quality_limits=config['quality'];dt=control['dt']
    m=mujoco.MjModel.from_xml_path(task['model']);d=mujoco.MjData(m);native=Stretch(m,binding)
    assert m.opt.timestep==dt and m.nmocap==0
    with np.load(output/'START.npz') as z:d.qpos[:]=z['qpos']
    d.qvel[:]=0
    sequence=phases(config,selected)
    # Validate every future native target before claiming any step.
    for phase in sequence:native.command(d,phase['target'])
    native.command(d,sequence[0]['target']);mujoco.mj_forward(m,d)
    root=binding['root_body'];base0=d.xpos[root].copy();object0=d.xipos[native.target].copy()
    length0=d.actuator_length.copy();warning0=d.warning.number.copy();gear=m.actuator_gear[:2,0]
    assert np.array_equal(gear,control['wheel_gear'])
    write(output/'EXECUTION_CONTRACT.json',dict(phases=sequence,dt=dt,initial_actuator_length=length0.tolist(),
         base_reference=base0.tolist(),object_com_reference=object0.tolist(),free_base=True,post_init_state_writes=0))
    gate=TaskGate();reference=None;total=0;gap=0.;result=[];stopped=False
    jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);floor=binding['floor_geom'];ground_allowed=set(binding['allowed_ground_robot_geoms']);wheels=set(binding['wheel_geoms'])
    vertices=np.array(task['local_vertices']);target_body=native.target
    def capture():
        return dict(time=float(d.time),qpos=d.qpos.copy(),qvel=d.qvel.copy(),actuator_length=d.actuator_length.copy(),
                    actuator_velocity=d.actuator_velocity.copy(),actuator_force=d.actuator_force.copy(),
                    object_com=d.xipos[target_body].copy(),object_position=d.xpos[target_body].copy(),object_rotation=d.xmat[target_body].reshape(3,3).copy(),
                    hand_position=d.xpos[native.hand].copy(),hand_rotation=d.xmat[native.hand].reshape(3,3).copy(),base_rotation=d.xmat[root].reshape(3,3).copy())
    def measure(phase, expected):
        cs=native.contacts(d);q=contact_quality(cs,d.xipos[target_body],d.xmat[target_body].reshape(3,3),task['mass_kg'],task['friction'][0])
        current=relative_pose(d.xpos[native.hand],d.xmat[native.hand],d.xipos[target_body],d.xmat[target_body])
        slip,rotation=(0.,0.) if reference is None else pose_drift(reference,current)
        ground=set();bad=[];pen=0.;ground_slip=0.;sf=0.;records=[]
        for i,c in enumerate(d.contact):
            g1,g2=int(c.geom1),int(c.geom2);b1,b2=map(int,m.geom_bodyid[[g1,g2]])
            force=np.zeros(6);mujoco.mj_contactForce(m,d,i,force);normal=max(0.,float(force[0]));pen=max(pen,-float(c.dist))
            records.append(dict(geoms=[g1,g2],bodies=[b1,b2],position=c.pos.tolist(),force=force.tolist(),distance=float(c.dist)))
            if target_body in (b1,b2):
                other=b2 if b1==target_body else b1
                if other==native.support:sf+=normal
                elif other not in native.hands:bad.append([g1,g2])
            if floor in (g1,g2):
                g=g2 if g1==floor else g1
                if int(m.geom_bodyid[g]) in native.robot:
                    if g not in ground_allowed:bad.append([g1,g2])
                    if normal>1e-4:ground.add(g)
                    if g in wheels and normal>1e-4:
                        mujoco.mj_jac(m,d,jp,jr,c.pos,int(m.geom_bodyid[g]));ground_slip=max(ground_slip,float(np.linalg.norm((jp@d.qvel)[:2])))
            elif b1 in native.robot or b2 in native.robot:
                if not (phase['allow_hand'] and target_body in (b1,b2) and (b1 in native.hands or b2 in native.hands)):bad.append([g1,g2])
        excess=0.
        for j in range(m.njnt):
            if m.jnt_limited[j]:
                v=d.qpos[m.jnt_qposadr[j]];lo,hi=m.jnt_range[j];tol=limits['slide_limit_tolerance_m'] if m.jnt_type[j]==mujoco.mjtJoint.mjJNT_SLIDE else limits['hinge_limit_tolerance_rad']
                excess=max(excess,float(lo-v-tol),float(v-hi-tol))
        r=d.xmat[target_body].reshape(3,3);bottom=float(np.min(vertices@r[2])+d.xpos[target_body,2]);va=binding['base_dof']
        object_velocity=np.zeros(6);mujoco.mj_objectVelocity(m,d,mujoco.mjtObj.mjOBJ_BODY,target_body,object_velocity,0)
        expected_xy=np.array(task['start'][:2])
        if phase['id'] in ('transport','place','release','retreat','settle'):
            expected_xy=expected_xy+(expected[3]-sequence[4]['target'][3])*np.array(selected['station']['inward'][:2])
        metric=dict(contact_quality=q,relative_slip_m=slip,relative_rotation_rad=rotation,object_lift_m=float(d.xipos[target_body,2]-object0[2]),
                    support_clearance_m=bottom-task['support_top_z'],support_force_N=sf,object_tilt_rad=float(np.arccos(np.clip(r[2,2],-1,1))),
                    object_xy_error_m=float(np.linalg.norm(d.xpos[target_body,:2]-expected_xy)),
                    object_speed_mps=float(np.linalg.norm(object_velocity[3:])),object_angular_speed_rps=float(np.linalg.norm(object_velocity[:3])),
                    object_goal_xy_error_m=float(np.linalg.norm(d.xpos[target_body,:2]-task['goal'][:2])),object_goal_z_error_m=float(abs(d.xpos[target_body,2]-task['goal'][2])),
                    base_tilt=float(np.arccos(np.clip(d.xmat[root].reshape(3,3)[2,2],-1,1))),base_xy=float(np.linalg.norm(d.xpos[root,:2]-base0[:2])),base_z=float(abs(d.xpos[root,2]-base0[2])),
                    base_speed=float(np.linalg.norm(d.qvel[va:va+3])),base_angular_speed=float(np.linalg.norm(d.qvel[va+3:va+6])),ground_any=bool(ground),both_wheels=wheels.issubset(ground),
                    ground_slip=ground_slip,penetration_m=pen,joint_excess=excess,unexpected_contacts=bad,
                    finite=bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()),warning_changed=bool(np.any(d.warning.number!=warning0)),max_speed=float(np.max(abs(d.qvel))))
        return metric,records
    for phase in sequence:
        if stopped:result.append(dict(id=phase['id'],status='skipped',steps=0));continue
        if phase['id'] in ('lift','transport'):gate.require_transport()
        out=output/phase['id'];out.mkdir();rows=[capture()];metrics=[];commands=[];targets=[];failed=[]
        with gzip.open(out/'CONTACTS.jsonl.gz','wt') as stream:
            for i in range(phase['steps']):
                target=target_at(phase,i+1,dt)
                raw=(control['wheel_kp']*((length0[:2]-d.actuator_length[:2])/gear)-control['wheel_kd']*(d.actuator_velocity[:2]/gear))/gear
                cmd=target.copy();cmd[:2]=np.clip(raw,-1,1)
                assert np.all(d.qfrc_applied==0) and np.all(d.xfrc_applied==0)
                native.command(d,cmd);commands.append(cmd.copy());targets.append(target.copy())
                mujoco.mj_step(m,d);mujoco.mj_forward(m,d);total+=1;rows.append(capture())
                v,contacts=measure(phase,target);metrics.append(v);stream.write(json.dumps(contacts)+'\n')
                gap=0. if v['ground_any'] else gap+dt
                checks=dict(finite=v['finite'],warnings=not v['warning_changed'],base_tilt=v['base_tilt']<=limits['max_tilt_rad'],
                    base_xy=v['base_xy']<=limits['max_xy_drift_m'],base_z=v['base_z']<=limits['max_z_drift_m'],
                    penetration=v['penetration_m']<=limits['max_penetration_m'],joints=v['joint_excess']<=0,contact_roles=not v['unexpected_contacts'],
                    ground=gap<=limits['max_ground_gap_seconds'],speed=v['max_speed']<=limits['max_generalized_speed_sanity'],
                    object_tilt=v['object_tilt_rad']<=quality_limits['max_object_tilt_rad'],object_xy=v['object_xy_error_m']<=quality_limits['max_object_xy_tracking_error_m'])
                if phase['id'] in ('lift','transport'):
                    checks.update(relative_slip=v['relative_slip_m']<=quality_limits['max_relative_slip_m'],relative_rotation=v['relative_rotation_rad']<=quality_limits['max_relative_rotation_rad'])
                failed=[k for k,ok in checks.items() if not ok]
                if failed:break
        arrays={k:np.array([r[k] for r in rows]) for k in rows[0]};arrays.update(ctrl=np.array(commands),target=np.array(targets))
        np.savez_compressed(out/'RAW.npz',**arrays)
        with gzip.open(out/'METRICS.json.gz','wt') as f:json.dump(metrics,f,allow_nan=False)
        if not failed:
            window=round(limits['final_window_seconds']/dt);tail=metrics[-window:]
            errors=np.max(abs(arrays['actuator_length'][-window:,2:]-np.array(phase['target'])[2:]),axis=0);mask=np.ones(6,bool)
            if phase['id'] in ('close','test_lift','test_hold','lift','transport','place'):mask[3]=False
            endpoint=dict(position_tracking=bool(np.all(errors[mask]<=np.array(limits['position_error_by_actuator'][2:])[mask])),
                ground=np.mean([v['both_wheels'] for v in tail])>=limits['min_final_both_wheels_ground_fraction'],
                wheel_error=np.max(abs(arrays['actuator_length'][-window:,:2]-length0[:2]))<=limits['max_final_wheel_coordinate_error_rad'],
                ground_slip=max(v['ground_slip'] for v in tail)<=limits['max_final_slip_mps'],base_speed=max(v['base_speed'] for v in tail)<=limits['max_final_base_linear_speed_mps'],
                base_angular_speed=max(v['base_angular_speed'] for v in tail)<=limits['max_final_base_angular_speed_rps'])
            failed=[k for k,ok in endpoint.items() if not ok]
            if phase['id']=='close':
                failed+=sorted({r for v in tail for r in contact_gate(v['contact_quality'],quality_limits)})
                reference=relative_pose(d.xpos[native.hand],d.xmat[native.hand],d.xipos[target_body],d.xmat[target_body])
            if phase['id']=='test_hold':failed+=gate.finish_test_lift(metrics,quality_limits,dt)
            if phase['id']=='settle':
                for key,bound in [('object_goal_xy_error_m',quality_limits['goal_xy_tolerance_m']),('object_goal_z_error_m',quality_limits['goal_z_tolerance_m']),('object_speed_mps',quality_limits['max_settled_speed_mps']),('object_angular_speed_rps',quality_limits['max_settled_angular_speed_rps'])]:
                    if max(v[key] for v in tail)>bound:failed.append(key)
                if min(v['support_force_N'] for v in tail)<.1:failed.append('final_support_contact')
                if max(v['contact_quality']['left']['force_N']+v['contact_quality']['right']['force_N'] for v in tail)>quality_limits['max_released_hand_force_N']:failed.append('hand_not_released')
        row=dict(id=phase['id'],status='fail' if failed else 'pass',steps=len(commands),failures=sorted(set(failed)),last_metrics=metrics[-1])
        write(out/'RESULT.json',row);print(json.dumps({k:row[k] for k in ('id','status','steps','failures')}),flush=True)
        result.append(row);stopped=bool(failed)
    assert total<=config['budget']['physics_steps_per_combination']
    final=dict(status='physical_failure' if stopped else 'full_pick_place_pass',phases=result,physics_steps=total,physical_attempts=1,
               test_lift_passed=gate.test_lift_passed,qualified_training_episodes=0,learning='unknown',no_post_init_state_writes=True)
    write(output/'EXECUTION_RESULT.json',final)
    return final
