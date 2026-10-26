"""Evidence-based continuation with anchored force/friction feedforward."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_ff import authorize as previous,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'DAMPED_WRIST_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=v['full_ticks'];return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_03/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'DAMPED_WRIST_PROTOCOL.json').exists();t=read_bound_json(root/'attempt_02/full/TRACE.json');r=read_bound_json(root/'attempt_02/full/REPORT.json');rows=t['records'][1194:];w=np.array([x['wrist_position_m'] for x in rows]);ledger=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in ledger['reservations']);F=((p['max_new_physics_steps']-spent+p['prefix_physics_steps'])//2)//4*4
    safe_save(root/'ATTEMPT_02_CAUSE.json',dict(report=_file_binding(root/'attempt_02/full/REPORT.json'),trace=r['trace'],new_physics_steps=0,wrist_span_m=np.ptp(w,axis=0).tolist(),hypothesis='After anchored finger/friction feedforward, realized load still fails while SONIC wrist pose moves. Existing wrist correction is pure integral. Add bounded reference P/I plus measured linear/angular velocity damping; body motors remain29SONIC, no arm override or motor feedforward.',limitation='Tests reference correction and measured disturbance hypothesis; not proof SONIC is incapable or that this will complete grasp.'))
    case=read_bound_json(Path(p['case']['path']));case['wrist_reference_feedback']='P.5/I.5 persecond/linear velocity damping.15s/angular.10s; original bias and perupdate step bounds retained';safe_save(root/'CASE_DAMPED.json',case)
    safe_save(root/'DAMPED_WRIST_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'FEEDFORWARD_PROTOCOL.json'),case=_file_binding(root/'CASE_DAMPED.json'),cause=_file_binding(root/'ATTEMPT_02_CAUSE.json'),tests=_file_binding(root/'WRIST_DAMPING_TESTS.xml'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-p['prefix_physics_steps'],full_replay_max=F,total_new_max=spent+2*F-p['prefix_physics_steps'],cumulative_max=p['prior_native_steps']+spent+2*F-p['prefix_physics_steps']),unchanged_deadline=p['deadline_epoch_utc'],not_a_version_count_stop=True,dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=spent),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);freeze(p.parse_args().root)
