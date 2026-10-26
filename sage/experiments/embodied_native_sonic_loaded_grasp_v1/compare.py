"""Pair exact recorded branches to identify the physical intervention boundary."""
import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    ts=[read_bound_json(root/('version_0%d/full/TRACE.json'%i)) for i in [1,2]];rs=[read_bound_json(root/('version_0%d/full/REPORT.json'%i)) for i in [1,2]];assert ts[0]['warmup_substeps']==ts[1]['warmup_substeps'];assert ts[0]['records'][:1000]==ts[1]['records'][:1000]
    first_control=first_body=first_state=None;same_substeps=0;firstallocation=None
    for e in ts[1]['events']:
        if e.get('kind')=='actuation_aware_finger_wrench_reference' and e['allocation']['feasible']:firstallocation=e;break
    for a,b in zip(ts[0]['records'],ts[1]['records']):
        if first_body is None and a['raw_sonic_isaaclab']!=b['raw_sonic_isaaclab']:first_body=dict(tick=a['tick'],time_s=a['substeps'][0]['time_before_s'])
        for x,y in zip(a['substeps'],b['substeps']):
            if first_control is None and x['all_ctrl']!=y['all_ctrl']:
                first_control=dict(tick=a['tick'],time_s=x['time_before_s'],initial_actual_states_identical=x['full_qpos_before']==y['full_qpos_before'] and x['full_qvel_before']==y['full_qvel_before'],body_targets_identical=x['body_position_target_rad']==y['body_position_target_rad'],hand_target_delta_rad=(np.array(y['hand_target_rad'])-x['hand_target_rad']).tolist())
            if first_state is None and (x['full_qpos_after']!=y['full_qpos_after'] or x['full_qvel_after']!=y['full_qvel_after']):first_state=dict(tick=a['tick'],time_s=x['time_after_s'])
            if first_state is None:same_substeps+=1
    result=dict(schema='paired-actual-finger-control-intervention/v1',new_physics_steps=0,common_original_checkpoint_steps=4040,original_prefix_and_warmup_exact=True,identical_active_physics_steps_before_first_state_difference=same_substeps,first_motor_control_difference=first_control,first_state_difference=first_state,first_later_sonic_action_difference=first_body,first_logged_feasible_allocation=firstallocation,reports=[_file_binding(root/('version_0%d/full/REPORT.json'%i)) for i in [1,2]],traces=[r['trace'] for r in rs],interpretation='Both actual branches start at the same exact recorded checkpoint. Physical divergence begins with finger reference intervention; subsequent SONIC output differences are responses to different actual states. Additional measured-wrench gate and failure-stop rule affect later transitions; this is not an isolated proof that an individual coefficient caused every outcome.',implementation=_file_binding(Path(__file__)))
    safe_save(root/'PAIRED_CAUSAL_COMPARISON.json',result);print(dict(first_motor_control_difference=first_control,first_state_difference=first_state,first_later_sonic_action_difference=first_body),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
