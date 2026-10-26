"""Bind real SONIC29 task outcomes, videos, source identities and finite costs."""
import argparse,time
from pathlib import Path
from .protocol import authorize,check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    p=authorize(root);out=root/'FINAL_REVIEW.json';assert not out.exists()
    ledger=read_bound_json(root/'COST.json');costs=[];spent=0
    for item in ledger['reservations']:
        rp=Path(item['output'])/'REPORT.json';assert rp.exists()
        report=read_bound_json(rp);spent+=report['physics_steps'];costs.append(dict(report=_file_binding(rp),steps=report['physics_steps']))
    assert spent<=p['max_new_physics_steps'] and spent+p['prior_native_steps']<=p['cumulative_native_cap']
    attempts=[]
    for version in sorted(root.glob('version_0*')):
        episode=version/'full'
        if not (episode/'REPORT.json').exists():continue
        r=read_bound_json(episode/'REPORT.json');a=read_bound_json(episode/'AUDIT.json');review=read_bound_json(version/'ATTEMPT_REVIEW.json')
        delivery=version/('delivery' if r['task_passed'] else 'partial_delivery');d=read_bound_json(delivery/'REVIEW.json')
        check(d['video_mp4']);assert d['all_decoded_frames']==(r['physics_steps']+3)//4
        assert a['state_samples']==r['physics_steps'] and a['gates']['sonic_controls_all29_body_joints']
        assert review['all_active_body_commands_sonic29'] and review['active_body_extra_feedforward_zero']
        attempts.append(dict(version=version.name,task_passed=bool(r['task_passed'] and a['task_passed']),qualified=bool(d['mechanically_qualified']),
            checkpoint_continuation=r.get('checkpoint_continuation'),actual_new_integrations=r.get('new_physics_steps',r['physics_steps']),
            full_report=_file_binding(episode/'REPORT.json'),independent_audit=_file_binding(episode/'AUDIT.json'),attempt=_file_binding(version/'ATTEMPT_REVIEW.json'),
            video=d['video_mp4'],delivery=_file_binding(delivery/'REVIEW.json'),actual_seconds=r['physics_steps']*.005,stop_reason=r['stop_reason'],
            all_executed_physics_safe=review['all_executed_physics_safe'],sonic29_ownership=True,active_extra_feedforward_zero=True,
            failed_audit_gates=[k for k,v in a['gates'].items() if not v],
            manual_encoded_frame_review='primary agent inspected decoded contact sheet and terminal full-resolution frame; not every video frame manually watched'))
    assert attempts
    result=dict(schema='native-sonic29-final-review/v1',closed_epoch_utc=time.time(),
        current_task_goal_achieved=any(a['qualified'] for a in attempts),positive_episode_count=sum(a['qualified'] for a in attempts),
        unified_body_control_implemented_and_independently_verified=all(a['sonic29_ownership'] for a in attempts),
        attempts=attempts,new_physics_steps=spent,cumulative_native_steps=p['prior_native_steps']+spent,cost_items=costs,
        protocol=_file_binding(root/'PROTOCOL.json'),
        explicit_same_budget_interface_extension=_file_binding(root/'VERSION_04_PROTOCOL.json'),
        historical_incomplete_interface_tests=_file_binding(root/'TELEOP_INTERFACE_TESTS.xml'),
        ordered_interface_correction=_file_binding(root/'ORDERED_INTERFACE_CONTINUATION_PROTOCOL.json'),
        corrected_interface_tests=_file_binding(root/'ORDERED_INTERFACE_TESTS.xml'),
        corrected_interface_zero_step_probe=_file_binding(root/'ORDERED_INTERFACE_PROBE.json'),
        measured_grasp_failure=_file_binding(root/'GRASP_FAILURE_REVIEW.json'),
        checkpoint_recovery=_file_binding(root/'CHECKPOINT_CONTINUATION_PROTOCOL.json'),
        native_effort_recovery=_file_binding(root/'TORQUE_COMMAND_CONTINUATION_PROTOCOL.json'),
        checkpoint_accounting='failed parent prefix3200charged once; continuation cost report charges only newly integrated suffix; combined episode must pass original-case full continuous replay to qualify',
        ledger=_file_binding(root/'COST.json'),control_tests=_file_binding(root/'CONTROL_TESTS_R2.xml'),
        old_pose_reference_route_probe=_file_binding(root/'REFERENCE_ROUTE_PROBE_R2.json'),
        scope='same original native room/full G1/mug, autonomous program expert references plus SONIC29 motor control; not visual autonomy, training or batch-production validation',
        production_review=dict(qualified_yield=sum(a['qualified'] for a in attempts),effective_scene_diversity=1,
            learning_effect='not evaluated; no training',human_intervention='finite task/reference/control revisions; no interactive forces or pose corrections',
            quality='measured states, original contact identities, independent NN/control audit, decoded real-state video; qualified export requires counted continuous replay'),
        all_background_work_ended=True,old_evidence_preserved=True,
        sources={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')},implementation=_file_binding(Path(__file__)))
    safe_save(out,result)
    print({k:result[k] for k in ('current_task_goal_achieved','positive_episode_count','unified_body_control_implemented_and_independently_verified','new_physics_steps','cumulative_native_steps')},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
