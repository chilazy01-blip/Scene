"""Normal-force continuity repair after measured middle-finger contact loss."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_top import authorize as previous,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'NORMAL_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_physics_steps=3972,prefix_active_ticks=983);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_05/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-3972;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'NORMAL_PROTOCOL.json').exists();tests=root/'NORMAL_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    cause=read_bound_json(root/'attempt_04/MEASURED_CAUSE.json');assert cause['gate_counts']['capacity_and_slip']==0
    case=read_bound_json(Path(p['case']['path']));case['normal_control_design']='Retain each screened group finger shape; lowpass measured FN tau.08s; persistent group closure integrates normal error gain.35 closure/(N s), deadband.05N, angular rate <=.006rad/20ms,0..halfclosed. Static current contact LP1.5mg proposes group normals within original6N cap, filtered tau.15s; no per-joint torque/current-q target substitution. Actual preload >=.8 group request5ticks then same capacity/wrench/10mm load/hover gates; original PD/native model unchanged.';safe_save(root/'CASE_NORMAL.json',case)
    source=root/'attempt_04/full';t=read_bound_json(source/'TRACE.json');N=983;assert t['records'][982]['stage']=='close';t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=3972,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'normal_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(x['safe'] for row in rows for x in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=3972,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in ledger['reservations']);F=((p['max_new_physics_steps']-spent+3972)//2)//4*4
    safe_save(root/'NORMAL_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'TOP_PROTOCOL.json'),case=_file_binding(root/'CASE_NORMAL.json'),cause=_file_binding(root/'attempt_04/MEASURED_CAUSE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-3972,full_replay_max=F,total_new_max=spent+2*F-3972,cumulative_max=p['prior_native_steps']+spent+2*F-3972),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
