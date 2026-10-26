"""Same physical task and native envelope, earlier verified-transport braking strategy."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_envelope import authorize as previous
from .protocol import read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'EARLY_BRAKE_PROTOCOL.json')
    for b in [v['previous_protocol'],v['plan'],v['case'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    return dict(p,case=v['case'],full_ticks=v['full_ticks'],prefix_active_ticks=v['prefix_active_ticks'],prefix_physics_steps=v['prefix_physics_steps'],prefix_report=v['prefix_report'],prefix_trace=v['prefix_trace'],prefix_io=v['prefix_io'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0;assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_27/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'EARLY_BRAKE_PROTOCOL.json').exists();plan=root/'EARLY_BRAKE_PLAN.json';a=read_bound_json(plan);N=a['prefix_active_ticks'];P=a['prefix_physics_steps'];assert a['actual_forward_carry_m']>=.25 and min(a['actual_foot_cycles'].values())>=1
    tests=root/'BRAKE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    case=read_bound_json(Path(p['case']['path']));case['base_arm_handoff_strategy']='After actual forward carry>=.25m and both original foot cycles>=1, begin the original75tick base brake. Keep original world cup goal and every original placement/release/stability gate. Reaching transport minimum alone is not success.';safe_save(root/'CASE_EARLY_BRAKE.json',case)
    source=root/'attempt_26/full';t=read_bound_json(source/'TRACE.json');t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=P,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'early_brake_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(physics_steps=P,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(Path(p['ledger_root'])/'COST.json');native=p['prior_native_steps']+spent_steps(ledger);F=((75000-native+P)//8)*4;assert native==65992 and N==1458 and P==5872 and F==7440
    names=('task_brake.py','test_brake.py','protocol_brake.py','engine_brake.py','audit_brake.py','replay_brake.py','visualize_brake.py','render_brake.py','delivery_brake.py')
    safe_save(root/'EARLY_BRAKE_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'NATIVE_ENVELOPE_PROTOCOL.json'),plan=_file_binding(plan),case=_file_binding(root/'CASE_EARLY_BRAKE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),prefix_active_ticks=N,prefix_physics_steps=P,full_ticks=(F-40)//4,dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},budget_proof=dict(native_spent=native,suffix_max=F-P,full_replay_max=F,projected_native_max=native+2*F-P),original_task_acceptance_unchanged=True,changed_strategy=case['base_arm_handoff_strategy']))
    print(dict(prepared=True,full_ticks=(F-40)//4,prefix=P,maximum_native=native+2*F-P),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
