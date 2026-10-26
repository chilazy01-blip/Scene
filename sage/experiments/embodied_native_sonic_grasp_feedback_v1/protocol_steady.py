"""Bounded straight carrying reference without avoidable pose/yaw perturbations."""
import argparse,time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .protocol_reserve import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'STEADY_CARRY_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks']);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_15/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-5488;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'STEADY_CARRY_PROTOCOL.json').exists();r=read_bound_json(root/'attempt_14/full/REPORT.json');assert r['grasp_test_passed'] and r['stop_reason']=='object_slipped';reserve_events=[e for e in r['events'] if e.get('kind')=='native_index0_original_halfclosed_reserve'];assert max(x['extra_reference_rad'] for x in reserve_events)>.023
    r13=read_bound_json(root/'attempt_13/full/REPORT.json');t=read_bound_json(root/'attempt_13/full/TRACE.json');a=[x for x in t['records'] if x['stage']=='carry'];points=np.array([x['wrist_reference_m'] for x in a]);base=np.array([x['substeps'][0]['full_qpos_before'][:3] for x in a]);yaw=np.unwrap([Rotation.from_quat(np.array(x['substeps'][0]['full_qpos_before'][3:7])[[1,2,3,0]]).as_euler('xyz')[2] for x in a]);speed=np.linalg.norm(np.diff(points,axis=0)/.02,axis=1);base_speed=np.linalg.norm(np.diff(base[:,:2],axis=0)/.02,axis=1);move=next(e for e in r['events'] if e.get('kind')=='cartesian_path' and e['tick']==1362);travel=float(np.linalg.norm(np.array(move['goal'])-move['origin']));tests=root/'STEADY_CARRY_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    safe_save(root/'STEADY_CARRY_CAUSE.json',dict(new_physics_steps=0,report=_file_binding(root/'attempt_14/full/REPORT.json'),walking_report=_file_binding(root/'attempt_13/full/REPORT.json'),walking_trace=r13['trace'],reference_wrist_speed_percentiles_m_s=np.percentile(speed,[50,95,100]).tolist(),base_speed_percentiles_m_s=np.percentile(base_speed,[50,95,100]).tolist(),reference_yaw_range_rad=float(np.ptp(yaw)),tuck_reference_travel_m=travel,tuck_reference_duration_ticks=60,observed='Original halfclosed index0 reserve was consumed, yet contact remains intermittent during the90mm tuck and slips during walking. Direct measured-base-yaw following injects side-to-side wrist targets faster than base translation.',change='Hold the already validated wrist grasp pose for the existing60tick carry-preparation period; then keep the carrying wrist world orientation/height and translate its target by base XY only. Left wrist/head references and official ordered lower12 walking inputs retained; SONIC owns all29 outputs. No virtual force/state/model/native limits or original task gates changed.',limitation='A reference-level control hypothesis. Removing avoidable reference disturbances does not guarantee a successful physical carry.'))
    case=read_bound_json(Path(p['case']['path']));case['steady_carry_policy']='Preserve validated grasp desired wrist pose through60tick carry preparation; straight-walk wrist reference follows baseXY translation only with fixed world orientation and height. Original fingers/native motor and all original physical/hover/carry/place/release/continuous replay gates unchanged.';safe_save(root/'CASE_STEADY_CARRY.json',case)
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-5488<=75000
    safe_save(root/'STEADY_CARRY_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'INDEX_RESERVE_PROTOCOL.json'),case=_file_binding(root/'CASE_STEADY_CARRY.json'),cause=_file_binding(root/'STEADY_CARRY_CAUSE.json'),tests=_file_binding(tests),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-5488,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-5488),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-5488),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
