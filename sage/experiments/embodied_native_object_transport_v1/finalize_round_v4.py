"""Bind the finite round's actual evidence and costs without rewriting old runs."""
import argparse
from pathlib import Path
import time
import xml.etree.ElementTree as ET
from .protocol_v5 import authorize
from .protocol_v4 import check
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def run(root):
    p=authorize(root);out=root/'ROUND_REVIEW.json';assert not out.exists()
    ledger=read_bound_json(root/'COST.json');actual=0;items=[];versions=[]
    for reservation in ledger['reservations']:
        rp=Path(reservation['output'])/'REPORT.json';assert rp.exists()
        report=read_bound_json(rp);actual+=report['physics_steps']
        items.append(dict(report=_file_binding(rp),actual_steps=report['physics_steps'],reserved_maximum=reservation['maximum_steps']))
    assert actual<=p['max_new_physics_steps'] and p['prior_native_steps']+actual<=p['cumulative_native_cap']
    for name in ('version_04','version_05'):
        episode=root/name/'full';r=read_bound_json(episode/'REPORT.json');a=read_bound_json(episode/'AUDIT.json')
        review=read_bound_json(root/name/'ATTEMPT_REVIEW.json')
        delivery=root/name/('delivery' if r['task_passed'] else 'partial_delivery')
        d=read_bound_json(delivery/'REVIEW.json')
        check(d['video_mp4'])
        assert review['executed_physics_steps']==a['state_samples']==r['physics_steps']
        assert d['all_decoded_frames']>0 and d['all_decoded_frames']==(r['physics_steps']+3)//4
        versions.append(dict(version=name,task_passed=bool(r['task_passed'] and a['task_passed']),
            qualified=bool(d['mechanically_qualified']),report=_file_binding(episode/'REPORT.json'),audit=_file_binding(episode/'AUDIT.json'),
            attempt_review=_file_binding(root/name/'ATTEMPT_REVIEW.json'),delivery=_file_binding(delivery/'REVIEW.json'),
            video=d['video_mp4'],seconds=r['physics_steps']*.005,stop_reason=r['stop_reason'],
            projection_ticks=r['projected_ticks'],maximum_projection_rad=r['maximum_target_projection_rad'],
            failed_audit_gates=[k for k,v in a['gates'].items() if not v],
            exact_pd_contact_geometry_reconstruction=max(a['max_pd_error_nm'],a['max_contact_error'],a['max_geometry_error_m'])==0,
            manual_review='encoded-frame contact sheet visually inspected by primary agent; not a claim of every video frame manually watched'))
    tests=ET.parse(root/'PROJECTION_TESTS.xml').getroot()
    suites=list(tests.iter('testsuite'))
    assert sum(int(s.get('tests','0')) for s in suites)==6
    assert all(int(s.get('failures','0'))==int(s.get('errors','0'))==0 for s in suites)
    result=dict(schema='native-mug-finite-round-review/v4',closed_epoch_utc=time.time(),
        overall_transport_goal_achieved=any(v['qualified'] for v in versions),positive_episode_count=sum(v['qualified'] for v in versions),
        versions=versions,new_physics_steps=actual,prior_native_steps=p['prior_native_steps'],cumulative_native_steps=p['prior_native_steps']+actual,
        cost_items=items,ledger=_file_binding(root/'COST.json'),protocol=_file_binding(root/'PROTOCOL.json'),revision=_file_binding(root/'VERSION_05_PROTOCOL.json'),
        tests=_file_binding(root/'PROJECTION_TESTS.xml'),unit_tests_passed=6,
        poststop_route_probe=_file_binding(root/'POSTSTOP_ROUTE_PROBE_V5.json'),
        route_probe_is_unexecuted=True,
        production_review=dict(quality='actual measured evidence and decoded MP4 only; failure samples excluded from positives',
            effective_diversity='one original native room, original mug and robot; two control versions are not two scene sources',
            qualified_yield=sum(v['qualified'] for v in versions),cost='recorded physical steps; audits/render/FK add no integrations',
            manual_intervention='two finite cause-driven versions and zero-step arm-route screening',learning_effect='not evaluated; no training',
            data_identity='development_validation, dataset_split unassigned; not heldout evaluation or batch production'),
        reusable_deliverables='legal-range action projection with true applied-action history, saturation telemetry and complete failed-attempt accounting',
        old_evidence_unchanged='parent v3 chain validated including every original source/model binding; old failures retain their original verdicts',
        no_background_work_remaining=True,
        sources={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')},implementation=_file_binding(Path(__file__)))
    safe_save(out,result)
    print({k:result[k] for k in ('overall_transport_goal_achieved','positive_episode_count','new_physics_steps','cumulative_native_steps')},flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
