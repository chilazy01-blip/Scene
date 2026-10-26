"""Independent generalized-force check of reconstructed contact wrench directions."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    import mujoco
    j=read_bound_json(root/'FRICTION_RECONSTRUCTION.json');trace=read_bound_json(Path(j['trace']['path']));model=load_model(j['model']['path']);model.opt.timestep=.005;data=mujoco.MjData(model);body=model.body('payload').id;dof=int(model.joint('payload_free').dofadr[0]);assert int(model.opt.cone)==0
    samples={s['time_after_s']:s for row in trace['records'] for s in row['substeps']};errors=[]
    for i,row in enumerate(j['rows']):
        if i%4:continue
        load_after(mujoco,model,data,samples[row['time_s']]);contact=np.array(row['hand_force_world_n'])+np.array(row['desk_force_world_n'])
        errors.append(float(np.max(np.abs(contact-data.qfrc_constraint[dof:dof+3]))))
    assert max(errors)<1e-8
    # All payload mass at body origin in this frozen model: independent Newton force balance.
    assert np.max(np.abs(model.body_ipos[body]))<1e-12
    force_errors=[]
    for row in [a for a in j['rows'] if 'static_capacity_contact_caps' in a]:
        load_after(mujoco,model,data,samples[row['time_s']]);lhs=np.array(row['net_contact_plus_gravity_n']);rhs=model.body_mass[body]*data.qacc[dof:dof+3]
        force_errors.append(float(np.max(np.abs(lhs-rhs))))
    assert max(force_errors)<1e-8
    safe_save(root/'INDEPENDENT_FORCE_CHECK.json',dict(schema='recorded-cup-wrench-independent-check/v1',new_physics_steps=0,cone_verified='pyramidal',
        checked_force_samples=len(errors),max_contact_force_vs_generalized_constraint_error_n=max(errors),max_newton_force_balance_error_n=max(force_errors),
        contact_force_sign_calibration=j['calibration']['desk_force_world_n'],known_weight_n=j['calibration']['weight_n'],
        friction_reconstruction=_file_binding(root/'FRICTION_RECONSTRUCTION.json'),implementation=_file_binding(Path(__file__))))
    print(dict(checked=len(errors),max_force_error=max(errors),max_newton_error=max(force_errors),new_physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
