"""Use physically feasible native contact wrench feedback inside original limits."""
import argparse,time
from pathlib import Path
from .protocol_steady import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'RELATIVE_WRENCH_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['preflight'],v['tests'],v['cause'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_16/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-5488;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'RELATIVE_WRENCH_PROTOCOL.json').exists();r=read_bound_json(root/'attempt_15/full/REPORT.json');assert r['grasp_test_passed'] and r['stop_reason']=='object_slipped';f=read_bound_json(root/'NATIVE_WRENCH_PREFLIGHT.json');assert f['initial_loaded_wrench_feasible'];tests=root/'RELATIVE_WRENCH_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    safe_save(root/'RELATIVE_WRENCH_CAUSE.json',dict(new_physics_steps=0,report=_file_binding(root/'attempt_15/full/REPORT.json'),trace=r['trace'],observed='Holding the validated wrist pose improves index continuity in preparation, but walking still loses contacts. Native actual-contact allocation for gravity-support wrench with original joint reference/effort and measured dry friction/passive/inertia is feasible at6 recorded loaded states. Scalar group closure cannot independently realize the feasible joint contact-torque allocation.',change='From the already validated strict-hover checkpoint, replace scalar finger-shape normal feedback with actual native6D contact-wrench allocation and persistent per-joint measured contact-torque error integration. Preserve cup COM/rotation relative to actual wrist using relative-motion damping, not absolute cup velocity. Existing halfclosed reference bounds and native PD/effort remain; maximum opening0.001rad/tick, any change0.006rad/tick; unloaded groups only reacquire within original bounds. The requested wrench is realized only via original motor PD, never applied as external force. Original acceptance slip anchor is not reset.',limitation='Actual-state feasibility does not prove dynamic tracking or a successful carry. No actual state/model/native parameter or original task-gate changes.'))
    case=read_bound_json(Path(p['case']['path']));case['relative_contact_wrench_policy']='From1362, supersede scalar normal/template/index-reserve updates with persistent per-joint force-error feedback to native actual-contact6Dwrench allocation; minimum normals thumb1.5/index0.75/middle1.5N; each joint stays original RIGHT_CLOSED*0.5 envelope, change<=0.006rad/20ms/opening<=0.001. Keep world-steady wrist carry and original load/hover/slip/carry/place/release/replay acceptance. No physical force injection.';safe_save(root/'CASE_RELATIVE_WRENCH.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-5488<=75000
    safe_save(root/'RELATIVE_WRENCH_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'STEADY_CARRY_PROTOCOL.json'),case=_file_binding(root/'CASE_RELATIVE_WRENCH.json'),cause=_file_binding(root/'RELATIVE_WRENCH_CAUSE.json'),preflight=_file_binding(root/'NATIVE_WRENCH_PREFLIGHT.json'),tests=_file_binding(tests),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-5488,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-5488),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-5488),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
