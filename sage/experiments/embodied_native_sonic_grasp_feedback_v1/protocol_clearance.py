"""Evidence-bound taller reference lift with original physical and task gates."""
import argparse,time
from pathlib import Path
from .protocol_continuous import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'CLEARANCE_LIFT_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['plan'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_12/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-4896;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'CLEARANCE_LIFT_PROTOCOL.json').exists();plan=read_bound_json(root/'CLEARANCE_LIFT_PLAN.json');assert plan['passed'] and plan['new_physics_steps']==0
    case=read_bound_json(Path(p['case']['path']));case['clearance_lift_policy']='75mm wrist lift relative to probe origin,98ticks, prior desired reference as path origin. Peak quintic reference speed no greater than previous40mm/60tick segment. Original measured25mm clearance,1s continuous hover and all force/slip/carry/release gates unchanged.';safe_save(root/'CASE_CLEARANCE_LIFT.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-4896<=75000
    safe_save(root/'CLEARANCE_LIFT_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'CONTINUOUS_LIFT_PROTOCOL.json'),case=_file_binding(root/'CASE_CLEARANCE_LIFT.json'),plan=_file_binding(root/'CLEARANCE_LIFT_PLAN.json'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-4896,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-4896),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-4896),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
