"""Stage-triggered continuity correction, retaining all physical and task criteria."""
import argparse
from pathlib import Path
import time
import numpy as np
from .protocol import authorize as previous,read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'STAGE_HOLD_PROTOCOL.json')
    for b in [v['cause'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    return dict(p,full_ticks=v['full_ticks'],prefix_active_ticks=v['prefix_active_ticks'],prefix_physics_steps=v['prefix_physics_steps'],prefix_report=v['prefix_report'],prefix_trace=v['prefix_trace'],prefix_io=v['prefix_io'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0
        assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_19/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'STAGE_HOLD_PROTOCOL.json').exists()
    cause=read_bound_json(root/'STAGE_SWITCH_CAUSE.json');assert cause['legacy_hold_bypassed'] and cause['original_strict_hover_passed']
    tests=root/'STAGE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    N=cause['first_tuck_tick'];P=40+4*N;source=root/'attempt_18/full';trace=read_bound_json(source/'TRACE.json');trace['records']=trace['records'][:N];trace['events']=[e for e in trace['events'] if e.get('tick',-1)<N];trace['rejected_command']=None
    trace['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=P,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'stage_hold_prefix';folder.mkdir();safe_save(folder/'TRACE.json',trace)
    io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files})
    rows=trace['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(physics_steps=P,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(Path(p['ledger_root'])/'COST.json');spent=spent_steps(ledger);native=p['prior_native_steps']+spent
    F=min(8920,((75000-native+P)//8)*4);assert F==8904 and native==62428
    names=('task_stage.py','test_stage.py','protocol_stage.py','engine_stage.py','audit_stage.py','replay_stage.py','visualize_stage.py','render_stage.py','delivery_stage.py','preview_stage.py')
    safe_save(root/'STAGE_HOLD_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'INTEGRATION_PROTOCOL.json'),cause=_file_binding(root/'STAGE_SWITCH_CAUSE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),prefix_active_ticks=N,prefix_physics_steps=P,full_ticks=(F-40)//4,dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},budget_proof=dict(native_spent=native,suffix_max=F-P,full_replay_max=F,projected_native_max=native+2*F-P),same_approved_deadline=p['deadline_epoch_utc'],change='Use the existing desired-grasp hold at every tuck stage, including a newly faster grip at1300; no absolute1362 clock gate. Same native SONIC29/hand14/acceptance.'))
    print(dict(prepared=True,prefix=N,prefix_physics=P,full_ticks=(F-40)//4,projected_native_max=native+2*F-P),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
