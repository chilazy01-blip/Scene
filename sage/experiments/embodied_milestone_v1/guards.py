"""Measured contact/task gates; no prescribed object pose is accepted as evidence."""
import numpy as np

GRASP_STAGES={'close','rise_lift','carry','stop_target','lower_place','release'}


def measure_task(c, metric, contacts, gap, stage):
    m=c.m;obj=m.geom('fb2_box_geom').id
    target=m.geom('fb2_target_top').id
    supports={m.geom('fb2_source_top').id,target}
    hands={s:{g for g in range(m.ngeom) if m.body(m.geom_bodyid[g]).name.startswith('gripper0_'+s)}
           for s in ['left','right']}
    forces={s:0. for s in hands};forbidden=[];on_target=False;ground_force=0.
    for row in contacts:
        pair=set(row['geoms']);active=row['force'][0]>1e-4 or row['distance'] < -1e-6
        robot=any(b in c.robot_bodies for b in row['bodies'])
        hand=next((s for s in hands if pair & hands[s]),None)
        allowed=(c.floor in pair and bool(pair & c.foot_ids)) or (obj in pair and bool(pair & supports))
        if obj in pair and hand:
            forces[hand]+=max(0.,row['force'][0])
            allowed=stage in GRASP_STAGES
        if robot and active and not allowed:forbidden.append(row['geoms'])
        if c.floor in pair:ground_force+=max(0.,row['force'][0])
        if pair=={obj,target} and row['force'][0]>1e-4:on_target=True
    checks=dict(finite=metric['finite'],warnings=not metric['warning_changed'],
                tilt=metric['tilt']<=.35,height=.50<=metric['height']<=.90,
                workspace=metric['xy_drift']<=1.8,penetration=metric['penetration']<=.01,
                forbidden_contact=not forbidden,joint_limits=metric['joint_limit_excess']<=0,
                joint_velocity=metric['joint_velocity_excess']<=0,generalized_velocity=metric['generalized_speed']<=50,
                ground_gap=gap<=.15,support_load=ground_force<=5*float(m.body_mass.sum())*9.81,
                grasp_force=max(forces.values())<=60,object_drop=c.d.qpos[52]>=.64)
    bad=[k for k,v in checks.items() if not v]
    p=c.d.qpos[50:53];speed=float(np.linalg.norm(c.d.qvel[49:52]))
    placed=np.linalg.norm(p[:2]-[1.05,0.])<=.03 and abs(p[2]-.71)<=.015 and speed<=.05 and on_target
    ready=True
    if stage in {'approach','stop_source'}:ready=np.linalg.norm(c.d.qpos[:2])<=.04
    if stage=='close':ready=min(forces.values())>=.05
    if stage in {'rise_lift','carry','stop_target'}:
        ready=p[2]>=.77 and min(forces.values())>=.05
        if stage in {'carry','stop_target'}:ready=ready and np.linalg.norm(p[:2]-[1.05,0.])<=.04
    if stage in {'lower_place','release','retract','rise_empty','settle_final'}:ready=placed
    if stage in {'release','retract','rise_empty','settle_final'}:ready=ready and max(forces.values())<.05
    if stage=='settle_final':ready=ready and metric['both_feet_ground'] and metric['slip']<=.05 and metric['base_linear_speed']<=.1
    metric.update(object_position=p.tolist(),object_velocity=c.d.qvel[49:55].tolist(),hand_force_N=forces,
                  target_support=on_target,unexpected_contacts=forbidden,support_force_N=ground_force,
                  ground_gap_seconds=gap,task_ready=bool(ready),stage=stage)
    return bad,bool(ready)


def final_window(metrics):
    if len(metrics)<500:return dict(passed=False,reason='missing_final_one_second')
    tail=metrics[-500:];p=np.array([v['object_position'] for v in tail]);velocity=np.array([v['object_velocity'] for v in tail])
    checks=dict(placement_xy=float(np.max(np.linalg.norm(p[:,:2]-[1.05,0.],axis=1)))<=.03,
                placement_z=float(np.max(abs(p[:,2]-.71)))<=.015,
                object_stable=float(np.max(np.linalg.norm(velocity[:,:3],axis=1)))<=.05,
                supported=float(np.mean([v['target_support'] for v in tail]))>=.95,
                feet=float(np.mean([v['both_feet_ground'] for v in tail]))>=.95,
                slip=max(v['slip'] for v in tail)<=.05,stopped=max(v['base_linear_speed'] for v in tail)<=.1)
    return dict(passed=all(checks.values()),checks=checks)
