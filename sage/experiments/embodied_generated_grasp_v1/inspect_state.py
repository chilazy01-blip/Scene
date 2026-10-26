"""Actual-state and private IK queries; no dynamics integration."""
from pathlib import Path
import numpy as np
from .common import ROOT,PREVIOUS,ORIGINAL,read_bound_json,_file_binding


def run(source,stage='release',sample='first',tick=None,goal=None,rotation=None):
    import mujoco as mj
    from sage.experiments.embodied_transport_native_v1.model import load_model
    from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
    from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
    from sage.experiments.embodied_native_object_transport_v1.kinematics_r3 import IK
    sources={'original_success':ORIGINAL/'trial_07',
             'previous_minus':PREVIOUS/'target_y_minus_30mm/codex_v2',
             'previous_plus':PREVIOUS/'target_y_plus_30mm/codex_v2'}
    folder=sources.get(source,ROOT/'trials'/source)
    if source not in sources and (not folder.resolve().is_relative_to(ROOT/'trials') or not(folder/'full/REPORT.json').exists()):raise ValueError('unknown inspect source')
    r=read_bound_json(folder/'full/REPORT.json');t=read_bound_json(Path(r['trace']['path']))
    if tick is not None:record=next(x for x in t['records'] if x['tick']==int(tick))
    else:
        rows=[x for x in t['records'] if x['stage']==stage]
        if not rows:raise ValueError('stage absent from actual trace')
        record=rows[0 if sample=='first' else -1 if sample=='last' else len(rows)//2]
    s=record['substeps'][-1]
    m=load_model(r['model']['path']);m.opt.timestep=.005;m.opt.noslip_iterations=3 if s['time_after_s']>19.800000001 else 0
    d=mj.MjData(m);d.qpos[:]=s['full_qpos_after'];d.qvel[:]=s['full_qvel_after'];d.ctrl[:]=s['all_ctrl'];d.qacc_warmstart[:]=s['qacc_warmstart_after'];d.time=s['time_after_s'];mj.mj_forward(m,d)
    cup=m.body('payload').id;w=m.body('right_wrist_yaw_link').id;cupR=d.xmat[cup].reshape(3,3);wR=d.xmat[w].reshape(3,3);h=hand_ids(m);contacts=[]
    for i,c in enumerate(d.contact):
        pair=contact_pair(m,c)
        if not any(x['name']=='payload_surface' for x in pair):continue
        force=np.zeros(6);mj.mj_contactForce(m,d,i,force)
        contacts.append(dict(pair=pair,point_world_m=c.pos.tolist(),normal_force_n=float(force[0]),force_local=force.tolist(),frame=c.frame.reshape(3,3).tolist()))
    out=dict(new_physics_steps=0,source=source,tick=record['tick'],stage=record['stage'],time_s=d.time,
        cup_world_m=d.xpos[cup].tolist(),cup_R=cupR.tolist(),cup_up=float(cupR[2,2]),cup_velocity=s['object_velocity_m_s'],cup_angular_velocity=s['full_qvel_after'][-3:],
        wrist_world_m=d.xpos[w].tolist(),wrist_R=wR.tolist(),cup_in_wrist_m=(wR.T@(d.xpos[cup]-d.xpos[w])).tolist(),cup_in_wrist_R=(wR.T@cupR).tolist(),
        root_m=d.qpos[:3].tolist(),hand_qpos=dict(zip(h['names'],d.qpos[h['qpos']].tolist())),hand_targets=dict(zip(h['names'],s['hand_target_rad'])),
        actual_forces=s['forces'],desk_supported=s['desk_supported'],hand_contact=s['hand_contact'],contacts=contacts,
        desired_wrist_m=record.get('wrist_reference_m'),report=_file_binding(folder/'full/REPORT.json'))
    if goal is not None:
        position=np.asarray(goal,dtype=float);R=np.asarray(rotation,dtype=float)
        if position.shape!=(3,) or R.shape!=(3,3) or not np.isfinite(np.r_[position,R.ravel()]).all():raise ValueError('invalid private IK query')
        out['private_IK_reference_query']=IK(mj,m).solve(d.qpos,position,R,max_evaluations=150)
    return out
