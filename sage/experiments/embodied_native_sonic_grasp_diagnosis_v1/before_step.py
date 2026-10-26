"""Reconstruct forces that generated the saved payload velocity increments, no steps."""
import argparse
from pathlib import Path
import numpy as np
from .friction import frame
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    j=read_bound_json(root/'FRICTION_RECONSTRUCTION.json');t=read_bound_json(Path(j['trace']['path']));r=read_bound_json(Path(j['report']['path']));case=read_bound_json(Path(r['case']['path']));model=load_model(j['model']['path']);model.opt.timestep=.005;d=mujoco.MjData(model);body=model.body('payload').id;dof=int(model.joint('payload_free').dofadr[0]);assert int(model.opt.integrator)==0 and np.max(np.abs(model.dof_damping[dof:dof+6]))==0
    rows=[];error=0.;force_error=0.
    for q in t['records']:
        if q['stage']!='lift':continue
        for s in q['substeps']:
            b=dict(s)
            for stem in ['full_qpos','full_qvel','qacc_warmstart']:b[stem+'_after']=s[stem+'_before']
            b['time_after_s']=s['time_before_s']
            actual=frame(mujoco,model,d,b,body,case)
            predicted=d.qvel[dof:dof+3]+.005*d.qacc[dof:dof+3]
            e=float(np.max(np.abs(predicted-np.array(s['full_qvel_after'])[dof:dof+3])));error=max(error,e)
            req=model.body_mass[body]*(np.array(s['full_qvel_after'])[dof:dof+3]-np.array(s['full_qvel_before'])[dof:dof+3])/.005
            force_error=max(force_error,float(np.max(np.abs(req-np.array(actual['net_contact_plus_gravity_n'])))))
            actual['saved_payload_velocity_increment_reconstruction_error_m_s']=e;rows.append(actual)
    assert error<1e-10 and force_error<1e-8
    result=dict(schema='actual-integration-contact-force-reconstruction/v1',new_physics_steps=0,physics_steps_reconstructed=len(rows),rows=rows,
        maximum_payload_velocity_prediction_error_m_s=error,maximum_force_vs_recorded_momentum_increment_error_n=force_error,
        interpretation='Recreated original pre-step state, warmstart and actually applied43ctrl; mj_forward only. Reconstructed acceleration predicts every recorded payload linear velocity increment under original Euler integrator with zero payload damping. No mj_step or new trajectory.',
        source_reconstruction=_file_binding(root/'FRICTION_RECONSTRUCTION.json'),implementation=_file_binding(Path(__file__)))
    safe_save(root/'ACTUAL_STEP_FORCE_CHECK.json',result);print(dict(rows=len(rows),maximum_velocity_error=error,maximum_force_error=force_error,new_physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
