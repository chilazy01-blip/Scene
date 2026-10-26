"""Use physically feasible native contact wrench feedback inside original limits."""
import argparse,time
from pathlib import Path
from .protocol_wrench import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'PRESERVED_WRENCH_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['preflight'],v['tests'],v['cause'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_17/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-5488;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'PRESERVED_WRENCH_PROTOCOL.json').exists();r=read_bound_json(root/'attempt_16/full/REPORT.json');assert r['grasp_test_passed'] and r['stop_reason']=='object_slipped';f=read_bound_json(root/'PRESERVED_WRENCH_PREFLIGHT.json');assert f['initial_loaded_wrench_feasible'];tests=root/'RELATIVE_WRENCH_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    safe_save(root/'PRESERVED_WRENCH_CAUSE.json',dict(new_physics_steps=0,report=_file_binding(root/'attempt_16/full/REPORT.json'),trace=r['trace'],observed='Actual6D LP feedback consumed closure to reduce normals toward1.5/0.75/1.5N, below the validated loaded grip preload. Recorded references opened and forces declined before loss. That new normal target policy failed to preserve grasp margin.',change='Capture minimum normals=max1.5N/actual measured loaded group normal at the strict-hover checkpoint. Solve the same native motor/contact wrench LP with these preserved group lower bounds. Maintain original PD/effort/halfclosed/rate/native physics and task gates. Independent audit and original-init43ctrl replay may run in parallel after a task-passed candidate; final export still requires both passed.',limitation='The preserved native allocation is statically feasible at the checkpoint; dynamic success remains unproven.'))
    case=read_bound_json(Path(p['case']['path']));case['preserved_wrench_policy']='Replace1362+ LP normal minima with max1.5N/actual loaded measured group norms captured once, keeping original validated preload. Same native per-joint force-error feedback and original halfclosed/PD/effort/physics/task/replay acceptance. Successful candidate audit and original-init43ctrl replay may verify independently in parallel; final export requires both.';safe_save(root/'CASE_PRESERVED_WRENCH.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-5488<=75000
    safe_save(root/'PRESERVED_WRENCH_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'RELATIVE_WRENCH_PROTOCOL.json'),case=_file_binding(root/'CASE_PRESERVED_WRENCH.json'),cause=_file_binding(root/'PRESERVED_WRENCH_CAUSE.json'),preflight=_file_binding(root/'PRESERVED_WRENCH_PREFLIGHT.json'),tests=_file_binding(tests),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-5488,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-5488),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-5488),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
