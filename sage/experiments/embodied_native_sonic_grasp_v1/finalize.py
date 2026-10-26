"""Bound measured correction and failures without claiming an achieved grasp."""
import argparse,os,time
from pathlib import Path
from .protocol import authorize,check
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    p=authorize(root);out=root/'FINAL_REVIEW.json';assert not out.exists()
    ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(a['output'])/'REPORT.json')['physics_steps'] for a in ledger['reservations'])
    assert spent==1316 and spent<=p['max_new_physics_steps'] and spent+p['prior_native_steps']<=p['cumulative_native_cap']
    attempts=[]
    for v,aname in [('version_01','AUDIT_R2.json'),('version_02','AUDIT.json')]:
        episode=root/v/'full';r=read_bound_json(episode/'REPORT.json');a=read_bound_json(episode/aname);d=read_bound_json(root/v/'partial_delivery/REVIEW.json');review=read_bound_json(root/v/'ATTEMPT_REVIEW.json')
        assert a['state_samples']==r['physics_steps']==4040+r['new_physics_steps']
        assert all(value for key,value in a['gates'].items() if key!='bounded_complete_episode')
        assert review['all_active_body_commands_sonic29'] and review['active_body_extra_feedforward_zero']
        assert not r['task_passed'] and not d['mechanically_qualified']
        assert d['all_decoded_frames']==(r['physics_steps']+3)//4;check(d['video_mp4'])
        details=read_bound_json(root/v/'grasp_detail/MANIFEST.json')
        for b in details['files'].values():check(b)
        attempts.append(dict(version=v,new_physics_steps=r['new_physics_steps'],recorded_episode_steps=r['physics_steps'],duration_s=r['physics_steps']*.005,
            stop_reason=r['stop_reason'],all_physical_gates_passed=review['all_executed_physics_safe'],checkpoint_continuation=r['checkpoint_continuation'],
            failed_audit_gates=[k for k,value in a['gates'].items() if not value],max_pd_reconstruction_error_nm=a['max_pd_error_nm'],max_contact_reconstruction_error=a['max_contact_error'],
            report=_file_binding(episode/'REPORT.json'),audit=_file_binding(episode/aname),attempt=_file_binding(root/v/'ATTEMPT_REVIEW.json'),delivery=_file_binding(root/v/'partial_delivery/REVIEW.json'),video=d['video_mp4'],detail=_file_binding(root/v/'grasp_detail/MANIFEST.json'),
            manual_review='agent inspected decoded video contact sheet, encoded full-resolution terminal frame and actual hand closeups; not every frame manually watched'))
    old=read_bound_json(root/'FINGER_DIAGNOSIS.json');new=read_bound_json(root/'FINGER_DIAGNOSIS_V2.json');assert not old['any_finger_saturation'] and not new['any_finger_saturation']
    def peak(j):return max(f['peak_abs_applied_nm'] for phase in j['phases'].values() for f in phase['joints'].values())
    active=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
        try:args=(proc/'cmdline').read_bytes().split(b'\0')
        except OSError:continue
        if b'-m' in args:
            i=args.index(b'-m')
            if i+1<len(args) and args[i+1].startswith(b'sage.experiments.embodied_native_sonic_grasp_v1.'):active.append(proc.name)
    assert not active,active
    result=dict(schema='native-sonic29-grasp-repair-final/v1',closed_epoch_utc=time.time(),current_task_goal_achieved=False,stable_off_table_grasp_achieved=False,positive_episode_count=0,
        correction_implemented='fixed measured-cup wrist target and per-thumb/index/middle contact-informed closure references; original SONIC29 and finger/body PD limits retained',
        verified_behavior_improvement='baseline index contact absent; corrected actual lift entry thumb2.3408N/index1.0312N/middle2.1413N. All three groups contact, but stable real lift still fails.',
        diagnosis=dict(original_finger_peak_torque_nm=peak(old),corrected_finger_peak_torque_nm=peak(new),any_native_finger_effort_saturation=False,
            known_limit='ordinary fingers1.4Nm,thumb0 2.45Nm; unchanged',
            conclusion='Rules out motors reaching their configured effort ceiling in these runs. Does not rule out insufficient commanded preload or poor contact-force allocation.',
            remaining='wrist/contact geometry, uneven contact heights and preload/friction-moment margin during lift. Group normal-force presence does not prove stable grasp; no unique cause proven.'),
        attempts=attempts,new_physics_steps=spent,cumulative_native_steps=p['prior_native_steps']+spent,
        no_continuous_replay_or_qualified_export='no complete successful native task; no replay integrations spent and no positive dataset exported',
        scope='one original native scene/full G1/triangle mesh mug, exact saved-prefix continuations; not fresh independent starts, visual autonomy or training',
        parent_review=p['parent_review'],protocol=_file_binding(root/'PROTOCOL.json'),final_correction_protocol=_file_binding(root/'VERSION_02_PROTOCOL.json'),ledger=_file_binding(root/'COST.json'),
        diagnosis_bindings={n:_file_binding(root/n) for n in ['FINGER_DIAGNOSIS.json','FINGER_DIAGNOSIS_V2.json','GRASP_GEOMETRY_PROBE.json','V1_CAUSAL_REVIEW.json','CONTACT_GEOMETRY_REVIEW.json','CONTACT_OPPOSITION_REVIEW.json']},
        regression_tests={n:_file_binding(root/n) for n in ['GRIP_TESTS.xml','GRIP_GROUP_TESTS.xml']},
        retained_failed_audit=_file_binding(root/'version_01/full/AUDIT.json'),zero_step_audit_lineage_correction=_file_binding(root/'POSTPROCESS_CORRECTION.json'),
        production_review=dict(quality='both executed segments pass measured physical gates, task/retention fail; real video and independent controls reconstructed',effective_scene_diversity=1,qualified_yield=0,actual_new_step_cost=spent,human_intervention='two bounded programmatic reference/gripper revisions, no physical state corrections or applied forces',learning_effect='not evaluated, no training'),
        scientific_exit='two declared correction versions completed; not physics-budget exhaustion. Retain regression; next bounded work should verify grasp geometry and loaded retention before repeating full transport.',
        all_background_work_ended=True,old_evidence_preserved=True,sources={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(out,result);print({k:result[k] for k in ['current_task_goal_achieved','positive_episode_count','new_physics_steps','cumulative_native_steps']},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
