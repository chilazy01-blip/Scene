"""Second and final measured grasp correction, unchanged finite budget and gates."""
import argparse,time
from pathlib import Path
from .protocol import authorize as parent,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding


def authorize(root):
    p=parent(root);v=read_bound_json(root/'VERSION_02_PROTOCOL.json')
    for b in [v['prior_protocol'],v['case'],v['cause_report'],v['cause_review'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=2299;return p


def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];ledger=read_bound_json(root/'COST.json')
    if output==root/'continuous_replay':charged=output;maximum=ceiling;replay=0
    else:
        assert output==root/'version_02/full' and ceiling==9236;charged=output.parent/'cost';maximum=ceiling-4040;replay=ceiling
    assert not any(q['output']==str(charged) for q in ledger['reservations'])
    spent=sum(read_bound_json(Path(q['output'])/'REPORT.json')['physics_steps'] if (Path(q['output'])/'REPORT.json').exists() else q['maximum_steps'] for q in ledger['reservations'])
    assert spent+maximum+replay<=p['max_new_physics_steps'] and spent+maximum+replay+p['prior_native_steps']<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=replay,reserved_epoch_utc=time.time()))
    safe_save(root/'COST.json',ledger)


def freeze(root):
    p=parent(root);out=root/'VERSION_02_PROTOCOL.json';assert not out.exists();cost=read_bound_json(root/'version_01/cost/REPORT.json');assert cost['physics_steps']==468
    case=read_bound_json(Path(p['case']['path']));case['grasp_repair']='fixed pre-close wrist target plus independent thumb/index/middle contact-informed position references, same original finger PD'
    safe_save(root/'CASE_V2.json',case)
    safe_save(out,dict(schema='native-sonic29-grasp-repair-final-v2',prior_protocol=_file_binding(root/'PROTOCOL.json'),deadline_epoch_utc=p['deadline_epoch_utc'],case=_file_binding(root/'CASE_V2.json'),cause_report=_file_binding(root/'version_01/full/REPORT.json'),cause_review=_file_binding(root/'V1_CAUSAL_REVIEW.json'),tests=_file_binding(root/'GRIP_GROUP_TESTS.xml'),
        change='Freeze measured-cup wrist target before closing. Each original finger group independently advances at most .2closure/s up to.5 only while its own normal contact is below thumb2N/index1N/middle1N; loaded groups pause instead of pushing while opposite groups close.',
        prelift_gate='at least1N thumb and1N index+middle, wrist reached, table supported, sustained25ticks; stronger than original.01N15ticks; no arbitrary requirement for third finger contact, final real off-table/carry/release unchanged',
        unchanged='same SONIC29, original finger/body PD gains, nativeeffort/joint limits, friction, geometry,4cm slip, all measured physical gates and final task acceptance',
        budget_proof=dict(already_new=468,new_suffix_max=5196,original_case_replay_max=9236,total_new_max=14900,prior_native=45086,cumulative_max=59986),
        exit='second final correction only; no further control versions or sweeps this round; preserve failed trajectories and scientific result',
        dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in ['grip_groups.py','task_v2.py','test_grip_groups.py','protocol_v2.py','v1_causal_review.py',*[x+'_v2.py' for x in ['engine','audit','visualize','render','closeout','review','replay']]]}))
    print(dict(frozen=True,version=2,exact_max_new_steps=14900,cumulative_max=59986),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
