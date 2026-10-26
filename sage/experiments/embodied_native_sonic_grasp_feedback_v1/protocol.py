"""Continue original goal within original global cap; versions are not a stop rule."""
import argparse,time,shutil
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.protocol import authorize as previous_authorize
from sage.experiments.embodied_native_sonic_grasp_v1.protocol import check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=read_bound_json(root/'PROTOCOL.json')
    for b in [p['plan'],p['case'],p['previous_review'],p['preflight'],p['tests'],p['prefix_report'],p['prefix_trace'],p['prefix_io'],*p['dependencies'].values()]:check(b)
    previous_authorize(Path(p['previous_root']))
    for b in read_bound_json(Path(p['previous_review']['path']))['sources'].values():check(b)
    return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];ledger=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output.name=='full' and output.parent.name.startswith('attempt_') and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and spent+maximum+headroom+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',ledger)

def freeze(root,previous):
    assert not (root/'PROTOCOL.json').exists();p=previous_authorize(previous);plan=read_bound_json(root/'PLAN.json');preflight=read_bound_json(root/'PREFLIGHT.json');assert preflight['passed']
    source=previous/'version_01/full';report=read_bound_json(source/'REPORT.json');case=read_bound_json(Path(report['case']['path']));case['feedback_control']='Measured cup-contact joint torque error integrates persistent finger equilibrium targets; originalKp/Kd and native joint damping remain active. Allocator accounts for actual native joint friction/passive/inertia in bounded motor feasibility; does not cancel damping in target reference.'
    safe_save(root/'CASE.json',case);t=read_bound_json(source/'TRACE.json');N=plan['prefix_active_ticks'];assert t['records'][N-1]['stage']=='close';t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=4816,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=4816,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    p=dict(p);p.update(plan);p.update(schema='sonic29-native-grasp-contact-feedback/v1',previous_root=str(previous),previous_review=_file_binding(previous/'FINAL_REVIEW.json'),plan=_file_binding(root/'PLAN.json'),case=_file_binding(root/'CASE.json'),preflight=_file_binding(root/'PREFLIGHT.json'),tests=_file_binding(root/'FEEDBACK_TESTS.xml'),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),reference_timing='Only post-checkpoint references: 10mm probe60ticks+10 check;50mm lift60ticks;1s real off-table hover; tuck60/place65/retract40; release60+10; unchanged actual physical/task acceptance.',feedback_design='admittance gain2/s, each target delta<=.006rad/20ms, original0..half-closed envelope; goal wrench includes gravity and mass-scaled critically damped object pose tracking. Old current-position torque target substitution is removed.',dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(root/'PROTOCOL.json',p);safe_save(root/'COST.json',dict(reservations=[],max_new_physics_steps=10504,prior_native_steps=49496,cumulative_cap=60000));print(dict(frozen=True,prefix4816_zero_new=True,first_suffix_max=2844,first_full_replay=7660,remaining_global_steps=10504),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--previous',type=Path,required=True);a=p.parse_args();freeze(a.root,a.previous)
