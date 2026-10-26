"""New user-authorized finite grasp round; retain all previous frozen evidence."""
import argparse,time
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_sonic_transport_v1.protocol_ordered import authorize as parent_authorize
from sage.experiments.embodied_native_sonic_transport_v1.rate_adapter import project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def check(b):assert sha256_file(Path(b['path']))==b['sha256'],b['path']

def authorize(root):
    p=read_bound_json(root/'PROTOCOL.json');assert p['schema']=='native-sonic29-grasp-repair/v1'
    for b in [p['plan'],p['parent_review'],p['case'],p['diagnosis'],p['geometry_probe'],p['tests'],p['prefix_report'],p['prefix_trace'],p['prefix_io'],*p['dependencies'].values()]:check(b)
    parent_authorize(Path(p['parent_root']))
    old=read_bound_json(Path(p['parent_review']['path']))
    for b in old['sources'].values():check(b)
    return p


def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];ledger=read_bound_json(root/'COST.json')
    if output==root/'continuous_replay':charged=output;maximum=ceiling
    else:
        assert output.parent.name in ['version_01','version_02'] and output.name=='full'
        assert ceiling<=9320;charged=output.parent/'cost';maximum=ceiling-4040
    assert not any(q['output']==str(charged) for q in ledger['reservations'])
    spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] if (Path(q['output'])/'REPORT.json').exists() else q['maximum_steps'] for q in ledger['reservations'])
    reserve_replay=0 if output==root/'continuous_replay' else ceiling
    assert spent+maximum+reserve_replay<=p['max_new_physics_steps'] and spent+maximum+reserve_replay+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=reserve_replay,reserved_epoch_utc=time.time()))
    safe_save(root/'COST.json',ledger)


def freeze(root,parent):
    assert not (root/'PROTOCOL.json').exists();previous=parent_authorize(parent);plan=read_bound_json(root/'PLAN.json')
    old=read_bound_json(parent/'FINAL_REVIEW.json');assert old['cumulative_native_steps']==plan['prior_native_steps']==45086
    case=read_bound_json(parent/'CASE_V4.json');probe=read_bound_json(root/'GRASP_GEOMETRY_PROBE.json');selected=probe['selected'];assert selected and len(selected['groups'])==3
    case['repair_grasp_local_xyz_m']=selected['offset_local_m'];case['grip_max_closure']=.50;case['stage_timeouts_ticks']['close']=350
    case['grasp_repair']='actual-cup translation alignment, thumb/index/middle geometry, same original finger PD with contact-informed bounded closure; SONIC29 unchanged'
    safe_save(root/'CASE.json',case)
    source=parent/'version_04_ordered/full';t=read_bound_json(source/'TRACE.json');t['records']=t['records'][:1000]
    last=t['records'][-1]['substeps'][-1];assert abs(last['time_after_s']-20.2)<1e-8 and t['records'][-1]['stage']=='insert'
    t['events']=[e for e in t['events'] if e.get('tick',-1)<1000];t['rejected_command']=None
    t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),source_report=_file_binding(source/'REPORT.json'),prefix_physics_steps=4040,prefix_active_ticks=1000,prepared_with_zero_integrations=True)
    folder=root/'prefix';folder.mkdir();safe_save(folder/'TRACE.json',t)
    io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:1000] for k in io.files})
    rr=t['records'];safe_save(folder/'REPORT.json',dict(schema='exact-recorded-prefix-not-a-new-episode/v1',physics_steps=4040,new_physics_steps=0,
        maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rr],axis=0).tolist(),
        maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rr),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rr),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    p=dict(previous);p.update(plan);p.update(schema='native-sonic29-grasp-repair/v1',parent_root=str(parent),parent_review=_file_binding(parent/'FINAL_REVIEW.json'),plan=_file_binding(root/'PLAN.json'),
        case=_file_binding(root/'CASE.json'),diagnosis=_file_binding(root/'FINGER_DIAGNOSIS.json'),geometry_probe=_file_binding(root/'GRASP_GEOMETRY_PROBE.json'),tests=_file_binding(root/'GRIP_TESTS.xml'),
        prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),
        full_ticks=2320,prefix_physics_steps=4040,prefix_active_ticks=1000,
        acceptance='same original real native full mug pickup/carry/release; qualified only after independent reconstruction, real video and original-case continuous43ctrl replay; exact checkpoint lineage disclosed',
        control_change='only real-cup wrist reference alignment and bounded contact-informed finger closure. Same SONIC29, original finger/body gains, friction, geometry, motor/physical limits.',
        dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(root/'PROTOCOL.json',p);safe_save(root/'COST.json',dict(reservations=[],max_physics_steps=14900,prior_native_steps=45086,cumulative_cap=60000))
    print(dict(frozen=True,prefix4040_no_new_steps=True,selected=selected['offset_local_m'],worst_first_run_plus_replay=14600,cumulative_worst=59686),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();freeze(a.root,a.parent)
