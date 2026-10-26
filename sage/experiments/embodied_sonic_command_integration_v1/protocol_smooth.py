"""Controlled test of measured delivered-reference jitter; shared native accounting."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_stage import authorize as previous
from .protocol import read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'SMOOTH_REFERENCE_PROTOCOL.json')
    for b in [v['cause'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    return dict(p,full_ticks=v['full_ticks'],prefix_active_ticks=v['prefix_active_ticks'],prefix_physics_steps=v['prefix_physics_steps'],prefix_report=v['prefix_report'],prefix_trace=v['prefix_trace'],prefix_io=v['prefix_io'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0;assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_20/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'SMOOTH_REFERENCE_PROTOCOL.json').exists()
    cause=read_bound_json(root/'REFERENCE_JITTER_CAUSE.json');assert cause['same_finger_motor_targets'] and cause['saturated_position_steps']==cause['steps_count']
    tests=root/'SMOOTH_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    source=root/'attempt_18/full';t=read_bound_json(source/'TRACE.json');N=next(i for i,a in enumerate(t['records']) if a['stage']=='loaded_hover');P=40+4*N
    t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=P,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'smooth_reference_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t)
    io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(physics_steps=P,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(Path(p['ledger_root'])/'COST.json');native=p['prior_native_steps']+spent_steps(ledger);F=min(8920,((75000-native+P)//8)*4)
    assert native==62468 and N==1250 and F==8784
    names=('wrist_smooth.py','task_smooth.py','test_smooth.py','protocol_smooth.py','engine_smooth.py','audit_smooth.py','replay_smooth.py','visualize_smooth.py','render_smooth.py','delivery_smooth.py','preview_smooth.py')
    safe_save(root/'SMOOTH_REFERENCE_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'STAGE_HOLD_PROTOCOL.json'),cause=_file_binding(root/'REFERENCE_JITTER_CAUSE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),prefix_active_ticks=N,prefix_physics_steps=P,full_ticks=(F-40)//4,dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},budget_proof=dict(native_spent=native,suffix_max=F-P,full_replay_max=F,projected_native_max=native+2*F-P),same_approved_deadline=p['deadline_epoch_utc'],change='Retain stage-aware desired-pose hold; activate same bounded reference P/I/velocity terms every20ms in loaded phases, filter velocity withtau120ms, cap correction slew20mm/s and120mrad/s. Native model/PD/effort/friction/hand targets and every original task gate unchanged.'))
    print(dict(prepared=True,prefix=N,prefix_physics=P,full_ticks=(F-40)//4,projected_native_max=native+2*F-P),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
