"""Explicit final released-interface bug fix, original limits/deadline retained."""
import argparse,time
from pathlib import Path
from .protocol_torque_resume import authorize as parent
from .rate_adapter import project_target
from .protocol import check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'ORDERED_INTERFACE_CONTINUATION_PROTOCOL.json')
    assert v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['parent_protocol'],v['cause_report'],v['cause_audit'],v['probe'],v['tests'],*v['official_sources'].values(),*v['dependencies'].values()]:check(b)
    return p


def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc']
    if output==root/'version_04_ordered/full':
        assert ceiling==8832;charged=root/'version_04_ordered/cost';maximum=5632
    else:
        assert output==root/'continuous_replay' and ceiling<=8832;charged=output;maximum=ceiling
    ledger=read_bound_json(root/'COST.json');assert not any(q['output']==str(charged) for q in ledger['reservations'])
    spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] if (Path(q['output'])/'REPORT.json').exists() else q['maximum_steps'] for q in ledger['reservations'])
    assert spent+maximum<=p['max_new_physics_steps'] and spent+maximum+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,reserved_at_epoch_utc=time.time(),actual_episode_output=str(output),prefix_already_charged_steps=3200 if maximum==5632 else 0))
    safe_save(root/'COST.json',ledger)


def freeze(root):
    p=parent(root);out=root/'ORDERED_INTERFACE_CONTINUATION_PROTOCOL.json';assert not out.exists() and time.time()<p['deadline_epoch_utc']
    probe=read_bound_json(root/'ORDERED_INTERFACE_PROBE.json');assert probe['corrected_lower_order'] and probe['maximum_requested_target_delta_rad']<.1
    ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] for q in ledger['reservations']);assert spent==15525
    src=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_data_stability_sonic_readmission_20261018_v1/source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref')
    safe_save(out,dict(schema='native-sonic29-released-lower-body-order-correction/v1',deadline_epoch_utc=p['deadline_epoch_utc'],
        parent_protocol=_file_binding(root/'TORQUE_COMMAND_CONTINUATION_PROTOCOL.json'),cause_report=_file_binding(root/'version_04_torque_resume/full/REPORT.json'),cause_audit=_file_binding(root/'version_04_torque_resume/full/AUDIT.json'),probe=_file_binding(root/'ORDERED_INTERFACE_PROBE.json'),tests=_file_binding(root/'ORDERED_INTERFACE_TESTS.xml'),
        plan_revision='Earlier native-effort branch scientific exit has fired and is preserved. Explicit final exception corrects a demonstrated implementation mismatch, not a speculative controller retune; publicly disclosed before new integration. User SONIC29/same task authorization persists, agent-authored version plan revised transparently. No further revision this round.',
        correction='Released CPP registry selects lower_body_joint_mujoco_order_in_isaaclab_index=[0,3,6,9,13,17,1,4,7,10,14,18]; previous adapter erroneously selected sorted Isaac lower-body indices. Correct only lower12 position/velocity horizon order; all other encoder blocks, NN models, physical/task gates, rate/effort bounds unchanged.',
        before_after_zero_step_delta_rad=[1.816,probe['maximum_requested_target_delta_rad']],
        checkpoint='exact original3200step prefix, previous5+8 failed branch steps excluded but charged. Corrected Task/NN/history restore; first corrected NN request must match zero-step probe bitwise.',
        accounting=dict(already_executed=15525,maximum_new_suffix_steps=5632,maximum_single_init_replay=8832,worst_total=29989,cap=30000,prior_native=28097,cumulative_cap=60000),
        qualification='same original mug task; independent NN/control/contact audit, real video, counted original-case one-initialization43ctrl continuous reintegration with no intermediate state injection required',
        exit='one corrected interface branch only; stop on real physical fault/task timeout or unchanged budget/deadline, preserve complete executed negative segment; no further versions this round',
        official_sources={n:_file_binding(src/f) for n,f in [('cpp','src/g1_deploy_onnx_ref.cpp'),('header','include/policy_parameters.hpp')]},
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ['protocol_ordered.py','teleop_reference_ordered.py','task_ordered.py','ordered_probe.py','test_teleop_ordered.py',*[x+'_ordered.py' for x in ['engine','audit','visualize','render','closeout','replay','review']]]}))
    print(dict(frozen=True,actual_spent=spent,worst_total=29989,new_physics_steps=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
