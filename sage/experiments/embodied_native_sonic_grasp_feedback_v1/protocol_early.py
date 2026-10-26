"""Latch at first measured capacity-qualified state instead of after prior unloading."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_grip import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'EARLY_GRIP_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=4760,prefix_active_ticks=1180);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_08/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-4760;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'EARLY_GRIP_PROTOCOL.json').exists();r=read_bound_json(root/'attempt_07/full/REPORT.json');assert r['stop_reason']=='probe_relative_slip';floors=[e for e in r['events'] if e.get('kind')=='loaded_grip_reference_floor'];assert floors and all(all(e['actual_closures'][g]>=e['previous_closures'][g] for g in e['actual_closures']) for e in floors)
    source=root/'attempt_05/full';t=read_bound_json(source/'TRACE.json');event=next(e for e in t['events'] if e.get('kind')=='actual_wrench_quality' and e.get('stage')=='force_balance' and e['quality']['qualified']);assert event['tick']==1180
    safe_save(root/'EARLY_GRIP_CAUSE.json',dict(new_physics_steps=0,failed_trial=_file_binding(root/'attempt_07/full/REPORT.json'),floor_events=floors,first_capacity_qualified_event=event,source_trace=_file_binding(source/'TRACE.json'),hypothesis='Attempt7 confirmed no reference opening during the load yet still slipped. Its floor was captured only at1194 after index preload reference had already decreased. Latch the identical monotonic closure floor at the first actually capacity-qualified state1180, before the preceding reduction. Keep the same15tick qualification and real10mm probe plus all actual load/hover/task gates. This tests timing of grip retention, not a proven unique cause.',limitation='Uses an exact development checkpoint. No claim of dynamic success until actual load/hover/carry and independent original-initialization replay.'))
    case=read_bound_json(Path(p['case']['path']));case['loaded_reference_floor']='Capture persistent group references from first actual capacity-qualified state tick1180; maintain monotonic closed-reference floor until release; same native PD and rate/envelope.';safe_save(root/'CASE_EARLY_GRIP.json',case)
    N=1180;t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=4760,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'early_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(x['safe'] for row in rows for x in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=4760,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-4760<=75000
    safe_save(root/'EARLY_GRIP_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'GRIP_HOLD_PLAN.json'),case=_file_binding(root/'CASE_EARLY_GRIP.json'),cause=_file_binding(root/'EARLY_GRIP_CAUSE.json'),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-4760,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-4760),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
