"""Keep the approved resource window and original task, fix loaded-walk references."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_clearance import authorize as previous,check,project_target
from .protocol import read_bound_json,safe_save,_file_binding

def authorize(root):
    p=previous(root);v=read_bound_json(root/'CARRY_WRIST_PROTOCOL.json')
    for b in [v['previous_protocol'],v['case'],v['cause'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    p=dict(p);p.update(case=v['case'],full_ticks=v['full_ticks'],prefix_active_ticks=1422,prefix_physics_steps=5728);return p

def reserve(root,output,ceiling):
    p=authorize(root);assert time.time()<p['deadline_epoch_utc'];l=read_bound_json(root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:charged=output;maximum=ceiling;headroom=0
    else:
        assert output==root/'attempt_13/full' and ceiling==40+4*p['full_ticks'];charged=output.parent/'cost';maximum=ceiling-5728;headroom=ceiling
    assert not any(x['output']==str(charged) for x in l['reservations']);spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in l['reservations'])
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    l['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(root/'COST.json',l)

def freeze(root):
    p=previous(root);assert not (root/'CARRY_WRIST_PROTOCOL.json').exists();source=root/'attempt_12/full';r=read_bound_json(source/'REPORT.json');assert r['grasp_test_passed'] and r['stop_reason']=='object_slipped';t=read_bound_json(source/'TRACE.json');N=1422;assert t['records'][N-1]['stage']=='tuck' and t['records'][N]['stage']=='carry' and t['records'][N]['wrist_reference_m'] is None
    rows=t['records'];walk=[x for x in rows if x['stage']=='carry'];offset=[(np.array(x['wrist_position_m'])-np.array(x['substeps'][-1]['root_m'])) for x in walk];drift=float(max(np.linalg.norm(x-offset[0]) for x in offset));tests=root/'CARRY_REFERENCE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    safe_save(root/'CARRY_WRIST_CAUSE.json',dict(report=_file_binding(source/'REPORT.json'),trace=r['trace'],new_physics_steps=0,grasp_hover_passed=True,carry_start_tick=N,all_carry_rows_lost_wrist_reference=all(x['wrist_reference_m'] is None for x in walk),maximum_wrist_to_base_offset_change_m=drift,actual_final_grasp_slip_m=r['max_held_slip_m'],observed='Loaded walk calls Task.walk, clears Cartesian path and returns to motion-joint encoder mode. Wrist base-relative offset then changes while index contact is already intermittent. This establishes the reference withdrawal and hand motion, not a unique cause of all slip.',change='Retain official ordered mode1 lower12 walking references plus right wrist/left wrist/head references during carry and braking. Capture previous desired pose at handoff; follow base XY/yaw with fixed world heights, desired wrist velocity follows horizontal base velocity. SONIC still owns all29 body actions; original fingers/physics/carry/slip/task criteria unchanged.'))
    case=read_bound_json(Path(p['case']['path']));case['loaded_walk_reference_policy']='Official ordered lower12 plus persistent wrist/head mode, previous desired wrist capture, base XY/yaw following, world heights fixed; native SONIC29 outputs and original strict load/hover/carry/place/release acceptance unchanged.';safe_save(root/'CASE_CARRY_WRIST.json',case)
    t['records']=rows[:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=r['trace'],prefix_physics_steps=5728,prefix_active_ticks=N,prepared_with_zero_integrations=True);folder=root/'carry_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=5728,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=r['trace']))
    l=read_bound_json(root/'COST.json');spent=sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] for x in l['reservations']);F=9040;assert p['prior_native_steps']+spent+2*F-5728<=75000
    safe_save(root/'CARRY_WRIST_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'CLEARANCE_LIFT_PROTOCOL.json'),case=_file_binding(root/'CASE_CARRY_WRIST.json'),cause=_file_binding(root/'CARRY_WRIST_CAUSE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),full_ticks=(F-40)//4,budget_proof=dict(spent=spent,new_suffix_max=F-5728,full_replay_max=F,projected_native_max=p['prior_native_steps']+spent+2*F-5728),unchanged_deadline=p['deadline_epoch_utc'],dependencies={x.name:_file_binding(x) for x in Path(__file__).parent.glob('*.py')}));print(dict(frozen=True,spent=spent,projected_native_max=p['prior_native_steps']+spent+2*F-5728),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);freeze(ap.parse_args().root)
