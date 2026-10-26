"""After verified load transfer, balance measured grip before a continuous lift."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_mesh import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'LOADED_BALANCE_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['preflight'],v['diagnosis'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=4896,prefix_active_ticks=1214);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_10/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-4896;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'LOADED_BALANCE_PROTOCOL.json').exists();source=root/'attempt_09/full';r=read_bound_json(source/'REPORT.json');assert r['load_probe_passed'] and not r['grasp_test_passed'] and r['stop_reason']=='loaded_relative_slip';f=read_bound_json(root/'LOADED_BALANCE_PREFLIGHT.json');assert f['proposed_balanced_preload']['feasible'] and f['custom_reference_bounds']['custom_template_motor_bound_passed'];tests=root/'LOADED_BALANCE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    case=read_bound_json(Path(p['case']['path']));case['loaded_balance_policy']='After actual unchanged load pass, maintain old wrist reference endpoint for>=25ticks; per-group minimum normal=max1.5N/actually observed load-pass supports; six-dimensional1.5weight allocation<=6N/group. Existing template halfclosed/angular-rate/native-effort unchanged. Require actual loaded quality/force and .8requested group preload15ticks, then lift from previous desired wrist reference for continuity. Original15mm loaded slip and all off-table/hover/carry/place/release gates unchanged.';safe_save(root/'CASE_LOADED_BALANCE.json',case)
    t=read_bound_json(source/'TRACE.json');N=1214;assert t['records'][N-1]['stage']=='load_probe';t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=4896,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'balanced_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=4896,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-4896<=75000
    safe_save(root/'LOADED_BALANCE_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'NATIVE_MESH_PROTOCOL.json'),case=_file_binding(root/'CASE_LOADED_BALANCE.json'),preflight=_file_binding(root/'LOADED_BALANCE_PREFLIGHT.json'),diagnosis=_file_binding(root/'attempt_09/MESH_LIFT_DIAGNOSIS.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-4896,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-4896),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-4896),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
