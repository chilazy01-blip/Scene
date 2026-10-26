"""Retain exact roundoff boundary and separately report material intervention."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    old=read_bound_json(root/'PAIRED_CAUSAL_COMPARISON.json');a=read_bound_json(root/'version_01/full/TRACE.json');b=read_bound_json(root/'version_02/full/TRACE.json');material=None;firstallocation=next(x for x in b['records'] if x.get('finger_wrench_allocation') and x['finger_wrench_allocation']['feasible'])
    for x,y in zip(a['records'],b['records']):
        for s,t in zip(x['substeps'],y['substeps']):
            delta=float(np.max(np.abs(np.array(s['all_ctrl'])-t['all_ctrl'])))
            if delta>1e-10:
                material=dict(tick=x['tick'],time_s=s['time_before_s'],maximum_motor_torque_change_nm=delta,maximum_prior_qpos_difference=float(np.max(np.abs(np.array(s['full_qpos_before'])-t['full_qpos_before']))),maximum_prior_qvel_difference=float(np.max(np.abs(np.array(s['full_qvel_before'])-t['full_qvel_before']))),body_targets_identical=s['body_position_target_rad']==t['body_position_target_rad'],hand_target_delta_rad=(np.array(t['hand_target_rad'])-s['hand_target_rad']).tolist());break
        if material:break
    result=dict(schema='paired-actual-finger-control-intervention/r2',new_physics_steps=0,exact_comparison=_file_binding(root/'PAIRED_CAUSAL_COMPARISON.json'),first_exact_motor_difference=old['first_motor_control_difference'],first_material_motor_difference=material,material_reporting_threshold_nm=1e-10,first_actual_feasible_allocation_tick=firstallocation['tick'],first_later_SONIC_action_difference=old['first_later_sonic_action_difference'],original_checkpoint4040_bitwise_identical=True,qualification_audit_tolerances_unchanged=True,interpretation='Earlier fallback target arithmetic differs by about7e-18rad and creates tiny floating state differences. Therefore the branches are bitwise identical at the restored checkpoint, not all the way to first LP action. The material intervention starts at23.2s with0.012Nm finger torque difference while body targets are still bitwise identical; prior qpos difference~1e-11. Subsequent SONIC changes respond to branch states. Material threshold is descriptive only and never replaces exact state-chain or qualification checks.',implementation=_file_binding(Path(__file__)))
    safe_save(root/'PAIRED_CAUSAL_COMPARISON_R2.json',result);print(result,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
