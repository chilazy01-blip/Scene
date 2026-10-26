"""Original contact, speed and terminal quality gates for native scene adaptation."""
import numpy as np
import mujoco
from sage.experiments.embodied_expert_task_v1.quality import kinematics,contacts

def measure(model,data,names,roles,limits,qpos_by_pin,command):
    k=kinematics(model,data,limits);c=contacts(model,data,names,roles,limits);violations=k['violations']+c['violations']
    joint_vel=data.qvel[qpos_by_pin-1];names_by_pin=[mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,int(np.flatnonzero(model.jnt_qposadr==address)[0])) for address in qpos_by_pin];hands=np.asarray([k for k,name in enumerate(names_by_pin) if name.startswith('gripper0_')]);arms=np.asarray([k for k,name in enumerate(names_by_pin) if k>=15 and name.startswith('robot0_')]);assert len(arms)==len(hands)==14
    arm_speed=float(np.max(np.abs(joint_vel[arms])));hand_speed=float(np.max(np.abs(joint_vel[hands])))
    if arm_speed>limits['max_arm_speed_rps']:violations.append('arm_speed')
    if hand_speed>limits['max_hand_speed_rps']:violations.append('hand_speed')
    feet=set();slip=[]
    for i in range(data.ncon):
        ct=data.contact[i]
        if {roles[ct.geom1],roles[ct.geom2]}!={'foot','floor'} or ct.dist>1e-5:continue
        gid=ct.geom1 if roles[ct.geom1]=='foot' else ct.geom2;ancestor=int(model.geom_bodyid[gid]);side=None
        while ancestor:
            body_name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,ancestor) or ''
            if 'left_ankle' in body_name:side='left';break
            if 'right_ankle' in body_name:side='right';break
            ancestor=int(model.body_parentid[ancestor])
        if side is None:raise ValueError('unclassified foot side')
        feet.add(side)
        body=int(model.geom_bodyid[gid]);jac=np.zeros((3,model.nv));mujoco.mj_jac(model,data,jac,None,ct.pos,body)
        at_contact=jac@data.qvel;slip.append(float(np.linalg.norm(at_contact[:2])))
    error=np.abs(data.qpos[qpos_by_pin]-command)
    return dict(**{k:v for k,v in k.items() if k!='violations'},contacts=c['contacts'],violations=sorted(set(violations)),max_arm_speed=arm_speed,max_hand_speed=hand_speed,feet_ground=sorted(feet),both_feet_ground=len(feet)==2,max_foot_slip=max(slip,default=0.),base_linear_speed=float(np.linalg.norm(data.qvel[:3])),base_angular_speed=float(np.linalg.norm(data.qvel[3:6])),lower_tracking=float(np.max(error[:15])),upper_tracking=float(np.max(error[arms])),hand_tracking=float(np.max(error[hands])),max_penetration=max([0.]+[-r['distance'] for r in c['contacts']]))

def terminal(rows,limits):
    if not rows:return dict(passed=False,violations=['missing_final_window'])
    last=rows[-1]['time'];window=[r for r in rows if r['time']>last-limits['final_window_seconds']+1e-9]
    metrics=dict(both_feet_ground_fraction=float(np.mean([r['both_feet_ground'] for r in window])),slip=max(r['max_foot_slip'] for r in window),linear_speed=max(r['base_linear_speed'] for r in window),angular_speed=max(r['base_angular_speed'] for r in window),lower_tracking=max(r['lower_tracking'] for r in window),upper_tracking=max(r['upper_tracking'] for r in window),hand_tracking=max(r['hand_tracking'] for r in window));bad=[]
    if metrics['both_feet_ground_fraction']<limits['min_final_both_feet_ground_fraction']:bad.append('final_ground_fraction')
    for key,limit in [('slip','max_final_slip_mps'),('linear_speed','max_final_base_linear_speed_mps'),('angular_speed','max_final_base_angular_speed_rps'),('lower_tracking','max_final_lower_tracking_error_rad'),('upper_tracking','max_final_upper_tracking_error_rad'),('hand_tracking','max_final_hand_tracking_error_rad')]:
        if metrics[key]>limits[limit]:bad.append('final_'+key)
    if len(window)<100:bad.append('incomplete_final_window')
    return dict(passed=not bad,violations=bad,frames=len(window),metrics=metrics)
