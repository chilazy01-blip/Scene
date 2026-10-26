"""Actual command/pre-state dynamic balance; no integration or counterfactual control."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .allocation import solve
from .quality import contacts
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_02/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');case=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);h=hand_ids(m);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);hd=h['dofs'][ix];other=np.array([i for i in range(m.nv) if i not in hd]);out=[]
    for tick in [1200,1220,1260,1280,1300]:
        row=t['records'][tick];s=row['substeps'][0];d.qpos[:]=s['full_qpos_before'];d.qvel[:]=s['full_qvel_before'];d.qacc_warmstart[:]=s['qacc_warmstart_before'];d.ctrl[:]=s['all_ctrl'];d.time=s['time_before_s'];mujoco.mj_forward(m,d)
        mass=np.zeros((m.nv,m.nv));mujoco.mj_fullM(m,d,mass)
        inertial=mass@d.qacc;rhs=d.qfrc_actuator+d.qfrc_passive+d.qfrc_constraint-d.qfrc_bias;err=float(np.max(np.abs(inertial[hd]-rhs[hd])));assert err<1e-7
        qrows,force=contacts(mujoco,m,d);proposal=row['finger_wrench_allocation'];assert proposal['feasible'] and not proposal['target_slew_limited']
        torque=np.array(s['finger_requested_torque_nm'])[ix];assert np.max(np.abs(torque-proposal['right_motor_torque_nm']))<1e-10
        target=np.array(s['hand_target_rad'])[ix];cancel=h['kd']*d.qvel[hd];identity=h['kp'][ix]*(target-d.qpos[h['qpos'][ix]])-cancel
        item=dict(tick=tick,time_s=s['time_before_s'],right_finger_joint_names=[h['names'][i] for i in ix],actual_velocity_rad_s=d.qvel[hd].tolist(),forward_acceleration_rad_s2=d.qacc[hd].tolist(),actual_motor_torque_nm=d.qfrc_actuator[hd].tolist(),actual_generalized_constraint_force_nm=d.qfrc_constraint[hd].tolist(),actual_bias_nm=d.qfrc_bias[hd].tolist(),actual_passive_nm=d.qfrc_passive[hd].tolist(),full_coupled_inertial_torque_nm=inertial[hd].tolist(),finger_motion_inertial_torque_nm=(mass[np.ix_(hd,hd)]@d.qacc[hd]).tolist(),other_body_motion_inertial_torque_nm=(mass[np.ix_(hd,other)]@d.qacc[other]).tolist(),maximum_dynamic_balance_error_nm=err,velocity_damping_cancelled_at_control_update_nm=cancel.tolist(),PD_identity_to_allocated_torque_error_nm=float(np.max(np.abs(identity-proposal['right_motor_torque_nm']))),actual_hand_force_world_n=force['hand_force_world_n'],actual_hand_torque_nm=force['hand_torque_nm'],desired_wrench=proposal['desired_wrench'])
        out.append(item);print(dict(tick=tick,velocity_max=float(np.max(np.abs(d.qvel[hd]))),inertial_torque_max=float(np.max(np.abs(inertial[hd]))),cancelled_damping_max=float(np.max(np.abs(cancel))),balance_error=err,handFz=force['hand_force_world_n'][2]),flush=True)
    safe_save(root/'ACTUAL_DYNAMIC_BALANCE.json',dict(schema='actual-finger-dynamic-balance/v1',new_physics_steps=0,rows=out,source_trace=r['trace'],interpretation='Reconstruct exact recorded before-state and actually sent43ctrl with mj_forward. M*qacc = actuator+passive+constraint-bias is checked in all7 right finger coordinates. Allocation assumes static bias+J.T*F; inertial/passive terms and coupled body dynamics are absent from that proposal. q_target=q+(tau_des+Kd*qvel)/Kp algebraically cancels sampled position and velocity feedback at each20ms allocation update; unchanged PD constants do not preserve the original effective impedance. This is a controller design limitation, not a proven sole explanation of every trajectory difference.',limitation='No new integration or changed command, no claim a damped correction has succeeded. Forward acceleration is the original forward-dynamics result; implicit Euler joint damping may make it differ from recorded velocity finite difference.',implementation=_file_binding(Path(__file__))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
