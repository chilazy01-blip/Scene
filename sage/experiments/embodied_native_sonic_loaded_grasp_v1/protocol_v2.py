"""Second and final causal correction, same deadline and13500 new step cap."""
import argparse,time
from pathlib import Path
from .protocol import authorize as parent,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_02_PROTOCOL.json')
    for b in [v['prior_protocol'],v['cause_review'],v['force_check'],v['preflight'],v['certificate'],v['case'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=v['full_ticks'];return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];ledger=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'version_02/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and spent+maximum+headroom+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom,reserved_epoch_utc=time.time()));safe_save(root/'COST.json',ledger)

def freeze(root):
    p=parent(root);assert not (root/'VERSION_02_PROTOCOL.json').exists();f=read_bound_json(root/'ALLOCATION_PREFLIGHT.json');cert=read_bound_json(root/'ALLOCATION_CERTIFICATE.json');assert f['feasible_count']==6 and cert['passed']
    cost=read_bound_json(root/'version_01/cost/REPORT.json')['physics_steps'];remaining=p['max_new_physics_steps']-cost;F=min(8348,((remaining+p['prefix_physics_steps'])//2)//4*4);ticks=(F-40)//4
    case=read_bound_json(Path(p['case']['path']));case['loaded_grasp_plan']='Actuation-aware6D gravity+moment contact LP mapped to original finger PD targets, own finger bias included in target mapping; original gains and native torque limits and0..half-closed target envelope; .006rad/20ms slew. Actual measured partial weight transfer and residual force/torque gate before10mm probe; same SONIC29.'
    safe_save(root/'CASE_V2.json',case)
    v=dict(schema='native-sonic29-loaded-grasp-final-v2',prior_protocol=_file_binding(root/'PROTOCOL.json'),case=_file_binding(root/'CASE_V2.json'),cause_review=_file_binding(root/'version_01/CAUSAL_REVIEW.json'),force_check=_file_binding(root/'version_01/FORCE_CHECK.json'),preflight=_file_binding(root/'ALLOCATION_PREFLIGHT.json'),certificate=_file_binding(root/'ALLOCATION_CERTIFICATE.json'),full_ticks=ticks,deadline_epoch_utc=p['deadline_epoch_utc'],control_change='Normal force totals and capacity alone did not realize feasible contact wrench. Solve contact forces with gravity and6D equilibrium plus actual finger Jacobian/original torque/target bounds; map to slew-limited PD reference. Require actual handFz>=.5mg, lateral<=.5mg, torque<=.02Nm together with capacity>=1.25 and low slip before probe. These are initial test gates, not manufacturer standards.',recovery_change='v1 lower/release caused cup fall. v2 rejects failed load test immediately as an incomplete negative; does not execute that unvalidated automatic release. No claim of completed recovery or stable long-term hold from an early stop.',budget_proof=dict(already_new_steps=cost,new_suffix_max=F-p['prefix_physics_steps'],original_case_replay_max=F,total_new_max=cost+2*F-p['prefix_physics_steps'],cumulative_max=p['prior_native_steps']+cost+2*F-p['prefix_physics_steps']),exit='second final control version; no additional controller revisions or grasp pose sweeps. Preserve all failures, stop for measured physical faults, only actual successful prefixes may be qualified by continuous43ctrl replay.',dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')})
    safe_save(root/'VERSION_02_PROTOCOL.json',v);print(dict(frozen=True,version=2,full_ticks=ticks,**v['budget_proof']),flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);freeze(a.parse_args().root)
