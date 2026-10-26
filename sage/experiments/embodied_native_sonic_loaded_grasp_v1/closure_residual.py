"""Numerically close omitted native finger friction/passive/inertial terms."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    dy=read_bound_json(root/'ACTUAL_DYNAMIC_BALANCE.json');co=read_bound_json(root/'ACTUAL_CONSTRAINT_DECOMPOSITION.json');rows=[]
    for d,c in zip(dy['rows'],co['rows']):
        assert d['tick']==c['tick'];motor=np.array(d['actual_motor_torque_nm']);bias=np.array(d['actual_bias_nm']);observed=-np.array(c['cup_contact_joint_torque_nm']);uncorrected=motor-bias
        passive=np.array(d['actual_passive_nm']);friction=np.array(c['constraint_parts_nm']['mjCNSTR_FRICTION_DOF']);inertial=np.array(d['full_coupled_inertial_torque_nm']);extra=np.array(c['other_contact_joint_torque_nm'])
        corrected=uncorrected+passive+friction-inertial+extra
        # A soft joint-limit reaction, if present, must also be included; absent here.
        limits=np.array(c['constraint_parts_nm']['mjCNSTR_LIMIT_JOINT']);assert np.max(np.abs(limits))==0
        err=float(np.max(np.abs(observed-corrected)));assert err<1e-12
        rows.append(dict(tick=d['tick'],time_s=d['time_s'],original_contact_only_mapping_error_nm=float(np.max(np.abs(observed-uncorrected))),error_after_including_actual_friction_passive_inertia_nm=err,maximum_native_dry_friction_reaction_nm=float(np.max(np.abs(friction))),maximum_inertial_term_nm=float(np.max(np.abs(inertial))),maximum_passive_term_nm=float(np.max(np.abs(passive))),maximum_other_contact_term_nm=float(np.max(np.abs(extra)))))
    result=dict(schema='actual-finger-motor-contact-balance-regression/v1',passed=True,new_physics_steps=0,native_joint_frictionloss_nm=co['native_dof_frictionloss_nm'],rows=rows,maximum_original_mapping_error_nm=max(r['original_contact_only_mapping_error_nm'] for r in rows),maximum_corrected_balance_error_nm=max(r['error_after_including_actual_friction_passive_inertia_nm'] for r in rows),formula='T_cup*lambda = tau_motor - bias + qfrc_passive + qfrc_joint_friction + qfrc_other_contacts - M*qacc; zero joint-limit reactions in these actual states',conclusion='v2 tau_motor=bias+T*lambda omits native joint dry friction, passive damping and coupled inertia. At these five actual unslewed commands joint dry friction dominates omitted terms. Correcting the force accounting closes the actual measured cup-contact joint torque, but no corrected controller or successful grasp has been dynamically validated.',dynamic_balance=_file_binding(root/'ACTUAL_DYNAMIC_BALANCE.json'),constraint_decomposition=_file_binding(root/'ACTUAL_CONSTRAINT_DECOMPOSITION.json'),implementation=_file_binding(Path(__file__)))
    safe_save(root/'ACTUAL_FORCE_BALANCE_REGRESSION.json',result);print(result,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
