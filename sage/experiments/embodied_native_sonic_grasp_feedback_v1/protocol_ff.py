"""Evidence-based continuation with anchored force/friction feedforward."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol import authorize as previous,check,project_target
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'FEEDFORWARD_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p['case']=v['case'];p['full_ticks']=v['full_ticks'];return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_02/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'FEEDFORWARD_PROTOCOL.json').exists();t=read_bound_json(root/'attempt_01/full/TRACE.json');r=read_bound_json(root/'attempt_01/full/REPORT.json');rows=t['records'][1194:];valid=[x for x in rows if x['feedback_allocation']['feasible']];desired=np.array([x['feedback_allocation']['desired_contact_torque_nm'] for x in valid]);err=np.array([np.array(x['feedback_allocation']['desired_contact_torque_nm'])-x['feedback_allocation']['measured_contact_torque_nm'] for x in valid]);w=np.array([x['wrist_position_m'] for x in rows]);cost=read_bound_json(root/'attempt_01/cost/REPORT.json')['physics_steps'];F=((p['max_new_physics_steps']-cost+p['prefix_physics_steps'])//2)//4*4
    safe_save(root/'ATTEMPT_01_CAUSE.json',dict(report=_file_binding(root/'attempt_01/full/REPORT.json'),trace=r['trace'],new_physics_steps=0,actual_new_steps=cost,feasible_control_ticks=len(valid),executed_control_ticks=len(rows),contact_torque_error_rms_nm=np.sqrt(np.mean(err*err,axis=0)).tolist(),mean_desired_torque_change_per20ms_nm=np.mean(np.abs(np.diff(desired,axis=0)),axis=0).tolist(),wrist_span_m=np.ptp(w,axis=0).tolist(),hypothesis='Measured force-error integral alone lagged moving contact/friction/pose disturbances. Add an anchored feedforward force/friction term with original PD impedance and the same .006rad target slew, rather than current-q torque substitution or a blind gain sweep.',limitation='Measured lack of convergence and disturbances; does not identify a unique global grasp solution or guarantee feedforward will succeed.'))
    case=read_bound_json(Path(p['case']['path']));case['feedback_control']='Fixed initial finger anchor + contact force and filtered joint-friction feedforward + measured contact-error integral; no qactual reference reset or Kd velocity cancellation, same original physical gains and limits.';safe_save(root/'CASE_FF.json',case)
    safe_save(root/'FEEDFORWARD_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'PROTOCOL.json'),case=_file_binding(root/'CASE_FF.json'),cause=_file_binding(root/'ATTEMPT_01_CAUSE.json'),tests=_file_binding(root/'IMPEDANCE_TESTS.xml'),full_ticks=(F-40)//4,budget_proof=dict(spent=cost,new_suffix_max=F-p['prefix_physics_steps'],full_replay_max=F,total_new_max=cost+2*F-p['prefix_physics_steps'],cumulative_max=p['prior_native_steps']+cost+2*F-p['prefix_physics_steps']),unchanged_deadline=p['deadline_epoch_utc'],not_a_version_count_stop=True,dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,full_ticks=(F-40)//4,spent=cost,reserved_total=cost+2*F-p['prefix_physics_steps']),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);freeze(p.parse_args().root)
