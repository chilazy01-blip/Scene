"""Bounded load qualification round; frozen original physics and causal sources."""
import argparse,time,json
from pathlib import Path
import numpy as np
from sage.experiments.embodied_native_sonic_grasp_v1.protocol_v2 import authorize as prior_authorize
from sage.experiments.embodied_native_sonic_grasp_v1.protocol import check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=read_bound_json(root/'PROTOCOL.json')
    for key in ['plan','case','prior_review','diagnosis_review','preload','screen','tests','prefix_report','prefix_trace','prefix_io']:
        check(p[key])
    for b in p['dependencies'].values():check(b)
    prior_authorize(Path(p['prior_root']))
    for fn in [p['prior_review']['path'],p['diagnosis_review']['path']]:
        for b in read_bound_json(Path(fn))['sources'].values():check(b)
    return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];ledger=read_bound_json(root/'COST.json')
    replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output.parent.name in ['version_01','version_02'] and output.name=='full'
        assert ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and spent+maximum+headroom+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom,reserved_epoch_utc=time.time()))
    safe_save(root/'COST.json',ledger)

def freeze(root,prior):
    assert not (root/'PROTOCOL.json').exists();p=prior_authorize(prior);plan=json.load(open(root/'PLAN.json'));safe_save(root/'PLAN.json',plan)
    z=read_bound_json(root/'BASELINE_PRELOAD.json')['required'];assert z['feasible']
    c=read_bound_json(Path(p['case']['path']));c['loaded_grasp_rotation']=np.eye(3).tolist();c['loaded_preload_targets_n']=z['required_group_normal_n'];c['stage_timeouts_ticks']['close']=350
    c['loaded_grasp_plan']='Retain actual baseline geometry after18 alternatives failed finite screen; fixed preclose wrist reference, wrench-derived per-group finger preload, actual6D capacity1.25 plus low slip,10mm1.2s load probe,50mm lift and1s real off-table hover; all29bodySONIC'
    safe_save(root/'CASE.json',c)
    source=prior/'prefix';folder=root/'prefix';folder.mkdir()
    import shutil
    for name in ['TRACE.json','REPORT.json','POLICY_IO.npz']:shutil.copyfile(source/name,folder/name)
    p=dict(p);p.update(plan);p.update(schema='native-sonic29-loaded-grasp/v1',prior_root=str(prior),prior_review=_file_binding(prior/'FINAL_REVIEW.json'),diagnosis_review=_file_binding(prior.parent/'embodied_native_sonic_grasp_diagnosis_20261022_v1/ROOT_CAUSE_REVIEW.json'),plan=_file_binding(root/'PLAN.json'),case=_file_binding(root/'CASE.json'),preload=_file_binding(root/'BASELINE_PRELOAD.json'),screen=_file_binding(root/'GEOMETRY_SCREEN_R3.json'),tests=_file_binding(root/'QUALITY_TESTS.xml'),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=2077,prefix_physics_steps=4040,prefix_active_ticks=1000,checkpoint_decision='Original plan reserved3200 prefix; use unchanged recorded4040 prefix because selected baseline reference before closing is identical. Saves800steps, already charged previously; no new integrations or forged states.',dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(root/'PROTOCOL.json',p);safe_save(root/'COST.json',dict(reservations=[],max_new_physics_steps=13500,prior_native_steps=46402,cumulative_cap=60000));print(dict(frozen=True,full_ceiling=8348,new_suffix=4308,replay=8348,total_new_max=12656),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);a.add_argument('--prior',type=Path,required=True);v=a.parse_args();freeze(v.root,v.prior)
