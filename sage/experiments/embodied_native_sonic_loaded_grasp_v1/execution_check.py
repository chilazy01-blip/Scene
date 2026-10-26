"""Check realized wrench after exactly applied unslewed allocated finger torque."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_sonic_grasp_diagnosis_v1.friction import frame
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_02/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');case=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);pid=m.body('payload').id;rows=[];allfeasible=[a for a in t['records'] if a.get('finger_wrench_allocation') and a['finger_wrench_allocation']['feasible']];errors=[]
    for row in allfeasible:
        z=row['finger_wrench_allocation'];s=row['substeps'][0];errors.append(float(np.max(np.abs(np.array(s['finger_requested_torque_nm'][7:])-z['right_motor_torque_nm']))))
    for tick in [1200,1220,1260,1280,1300]:
        row=t['records'][tick];z=row['finger_wrench_allocation'];s=row['substeps'][0];assert z['feasible'] and not z['target_slew_limited'];tau=np.array(s['finger_requested_torque_nm'][7:]);err=float(np.max(np.abs(tau-z['right_motor_torque_nm'])));assert err<1e-10
        force=frame(mujoco,m,d,s,pid,case,True)
        rows.append(dict(tick=tick,time_s=s['time_after_s'],actual_PD_to_desired_torque_max_error_nm=err,actual_actuator_force_to_requested_error_nm=float(np.max(np.abs(np.array(s['actual_finger_actuator_force_nm'][7:])-tau))),desired_object_wrench=z['desired_wrench'],actual_hand_force_world_n=force['hand_force_world_n'],actual_hand_torque_about_com_nm=force['hand_torque_about_com_nm'],actual_desk_force_world_n=force['desk_force_world_n'],actual_contact_capacity=force['static_capacity_contact_caps']));print(rows[-1],flush=True)
    result=dict(schema='allocated-finger-torque-versus-real-object-wrench/v1',new_physics_steps=0,actual_feasible_allocation_ticks=len(allfeasible),slew_limited_ticks=sum(a['finger_wrench_allocation']['target_slew_limited'] for a in allfeasible),median_motor_torque_mapping_error_nm=float(np.median(errors)),maximum_mapping_error_nm=max(errors),examples=rows,interpretation='These five commands reached the requested finger motor torques without reference slew clipping; actual after-step cup wrench still differs strongly from the static proposal. This rules out mere failure to send those motor requests. Static hand-joint torque compatibility alone does not establish the desired world contact wrench in the moving, table-supported coupled system. It does not isolate all contact compliance, joint inertia, nullspace or whole-body tracking contributions.',report=_file_binding(ep/'REPORT.json'),trace=r['trace'],implementation=_file_binding(Path(__file__)))
    safe_save(root/'ALLOCATION_EXECUTION_CHECK.json',result)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
