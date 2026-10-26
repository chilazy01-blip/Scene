"""Use original probe-to-lift acceptance with continuous references and loaded preload."""
import argparse,time
from pathlib import Path
from .protocol_balanced import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'CONTINUOUS_LIFT_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_11/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-4896;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'CONTINUOUS_LIFT_PROTOCOL.json').exists();r=read_bound_json(root/'attempt_10/full/REPORT.json');assert r['stop_reason']=='loaded_balance_not_stable';events=[e for e in r['events'] if e.get('kind')=='actual_wrench_quality' and e.get('stage')=='loaded_balance'];early=[e for e in events if e['tick']<=1245];assert early and all(e['quality']['qualified'] and e['quality']['hand_force_world_n'][2]>=.8*e['quality']['weight_n'] and e['quality']['desk_force_z_n']<.01 for e in early)
    safe_save(root/'CONTINUOUS_LIFT_CAUSE.json',dict(new_physics_steps=0,report=_file_binding(root/'attempt_10/full/REPORT.json'),early_real_loaded_quality=early,observed='After strict actual load pass, global hand support and capacity/slip remained qualified for the first0.6s, while the added per-group target gate did not complete. Prolonged low-height holding later recontacted the table. Requests are control targets, not original success criteria.',change='Restore original strict probe-to-lift workflow. Retain the verified loaded preload adjustment within existing native reference/motor bounds and use previous DESIRED wrist pose as new lift origin for command continuity. No added per-group readiness gate. All original actual load/relative-slip/off-table/1s hover/both-foot carry/place/release/continuous-replay acceptance unchanged.',limitation='This removes only an extra intermediate gate introduced in attempt10; no original physical or task acceptance is weakened, and success remains to be demonstrated.'))
    case=read_bound_json(Path(p['case']['path']));case['loaded_balance_policy']='After original strict load pass directly start original lift60ticks, adjust actual loaded normal targets as verified, origin=previous desired wrist pose; no extra per-group readiness stage. Original load/slip/height/hover/full task and native limits unchanged.';safe_save(root/'CASE_CONTINUOUS_LIFT.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-4896<=75000
    safe_save(root/'CONTINUOUS_LIFT_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'LOADED_BALANCE_PROTOCOL.json'),case=_file_binding(root/'CASE_CONTINUOUS_LIFT.json'),cause=_file_binding(root/'CONTINUOUS_LIFT_CAUSE.json'),tests=_file_binding(root/'LOADED_BALANCE_TESTS.xml'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-4896,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-4896),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-4896),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
