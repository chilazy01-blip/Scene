"""One exact-checkpoint software recovery, no new task reset or budget extension."""
import argparse,time
from pathlib import Path
from .protocol_resume import authorize as parent
from .rate_adapter import project_target
from .protocol import check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'TORQUE_COMMAND_CONTINUATION_PROTOCOL.json')
    assert v['maximum_new_continuation_steps']==5640 and v['deadline_epoch_utc']==p['deadline_epoch_utc']
    for b in [v['parent_protocol'],v['parent_report'],v['parent_audit'],v['restore_probe'],v['rate_tests'],v['negative_branch'],v['native_effort_probe'],*v['dependencies'].values()]:check(b)
    return p


def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('unchanged round deadline')
    if output==root/'version_04_torque_resume/full':
        assert ceiling==8840;charged_output=root/'version_04_torque_resume/cost';maximum=5640
    else:
        assert output==root/'continuous_replay' and ceiling<=8840;charged_output=output;maximum=ceiling
    ledger=read_bound_json(root/'COST.json');assert not any(q['output']==str(charged_output) for q in ledger['reservations'])
    spent=0
    for q in ledger['reservations']:
        rp=Path(q['output'])/'REPORT.json';spent+=read_bound_json(rp)['physics_steps'] if rp.exists() else q['maximum_steps']
    assert spent+maximum<=p['max_new_physics_steps'] and spent+maximum+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged_output),maximum_steps=maximum,reserved_at_epoch_utc=time.time(),
        actual_episode_output=str(output),prefix_already_charged_steps=3200 if maximum==5640 else 0))
    safe_save(root/'COST.json',ledger)


def freeze(root):
    p=parent(root);out=root/'TORQUE_COMMAND_CONTINUATION_PROTOCOL.json';assert not out.exists()
    effort_probe=read_bound_json(root/'NATIVE_EFFORT_COMMAND_PROBE.json');assert effort_probe['mismatches']
    probe=read_bound_json(root/'EXACT_CHECKPOINT_PROBE.json');audit=read_bound_json(root/'version_04/full/AUDIT.json')
    assert probe['restored_state_exact'] and probe['refused_command_bitwise_reproduced'] and audit['executed_control_reconstruction_passed']
    cost=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] for q in cost['reservations']);assert spent==15517
    safe_save(out,dict(schema='native-sonic29-exact-checkpoint-continuation/v1',deadline_epoch_utc=p['deadline_epoch_utc'],
        parent_protocol=_file_binding(root/'CHECKPOINT_CONTINUATION_PROTOCOL.json'),negative_branch=_file_binding(root/'version_04_resume/full/REPORT.json'),native_effort_probe=_file_binding(root/'NATIVE_EFFORT_COMMAND_PROBE.json'),parent_report=_file_binding(root/'version_04/full/REPORT.json'),parent_audit=_file_binding(root/'version_04/full/AUDIT.json'),
        restore_probe=_file_binding(root/'EXACT_CHECKPOINT_PROBE.json'),rate_tests=_file_binding(root/'COMMAND_ADAPTER_TESTS.xml'),
        authorized_scope='same current user task/SONIC29 control; recover an unexecuted command-layer refusal, exactly restore saved dynamics and histories, preserve the failed parent',
        accounting='no fresh case or prefix reintegration. Parent3200steps already charged. Continuation cost report charges only actual new suffix; combined trace separately retains source lineage.',
        maximum_new_continuation_steps=5640,maximum_complete_episode_steps=8840,
        budget_proof=dict(already_executed=15517,continuation_max=5640,original_case_replay_max=8840,worst_total=29997,unchanged_cap=30000),
        native_effort_fix='body torque command clipped to intersection of released effort and actual native ctrlrange; MuJoCo model/gains/limits unchanged; prior5-step failed branch excluded and preserved',
        patch='SONIC targets clip to original real ranges then per-joint original .543398784rad/20ms command delta; record actual clipped command in policy history, no slew-only abort',
        all_physical_gates_and_task_criteria_unchanged=True,
        continuity_proof_required='all zero-step restored states match bitwise, refused NN request bitwise reproduced; qualified export requires original-case one-init full43ctrl continuous replay with zero error and no intermediate injections',
        exit='one native-command-limit repair branch from original exact16s checkpoint, do not include negative5-step branch; stop on real physical fault/task timeout/global cap. No further recovery under this protocol.',
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ('protocol_torque_resume.py','restore.py','rate_adapter.py','effort_adapter.py','effort_probe.py','engine_torque_resume.py','audit_torque_resume.py','visualize_torque_resume.py','closeout_torque_resume.py','replay_torque_resume.py','review_torque_resume.py','test_effort_adapter.py','render_torque_resume.py')}))
    print(dict(frozen=True,additional_steps_max=5640,worst_round_steps=29997,new_integrations=0),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
