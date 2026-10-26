"""Explicitly separate a wider expert reference envelope from physical/task limits."""
import argparse,time
from pathlib import Path
import numpy as np
from .protocol_fast import authorize as previous
from .protocol import read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'NATIVE_ENVELOPE_PROTOCOL.json')
    for b in [v['previous_protocol'],v['preflight'],v['case'],v['tests'],v['prefix_report'],v['prefix_trace'],v['prefix_io'],*v['dependencies'].values()]:check(b)
    return dict(p,case=v['case'],full_ticks=v['full_ticks'],prefix_active_ticks=v['prefix_active_ticks'],prefix_physics_steps=v['prefix_physics_steps'],prefix_report=v['prefix_report'],prefix_trace=v['prefix_trace'],prefix_io=v['prefix_io'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0;assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_26/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'NATIVE_ENVELOPE_PROTOCOL.json').exists();pre=root/'NATIVE_ENVELOPE_PREFLIGHT.json';assert read_bound_json(pre)['restored_feasible_states']>=1
    tests=root/'ENVELOPE_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    case=read_bound_json(Path(p['case']['path']));case['loaded_native_reference_ratio']=.65;case['loaded_reference_extension_after_carry_ticks']=40;case['control_regime']='Original pre-grasp/hover and first40loaded walking ticks retain the old0.5reference envelope. Thereafter permit0.65of the original finger closing template within unchanged native joint ranges and motor effort/PD/friction. This changes an expert action envelope, not physical limits or task acceptance. Results must not be described as success under the old0.5condition.';safe_save(root/'CASE_NATIVE_ENVELOPE.json',case)
    source=root/'attempt_25/full';t=read_bound_json(source/'TRACE.json');N=1400;P=40+4*N;t['records']=t['records'][:N];t['events']=[e for e in t['events'] if e.get('tick',-1)<N];t['rejected_command']=None;t['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=P,prefix_active_ticks=N,prepared_with_zero_integrations=True)
    folder=root/'native_envelope_prefix';folder.mkdir();safe_save(folder/'TRACE.json',t);io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:N] for k in io.files});rows=t['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(physics_steps=P,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(Path(p['ledger_root'])/'COST.json');native=p['prior_native_steps']+spent_steps(ledger);F=((75000-native+P)//8)*4
    assert native==65716 and P==5640 and F==7460
    names=('native_envelope.py','task_envelope.py','test_envelope.py','protocol_envelope.py','engine_envelope.py','audit_envelope.py','replay_envelope.py','visualize_envelope.py','render_envelope.py','delivery_envelope.py')
    safe_save(root/'NATIVE_ENVELOPE_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'FAST_CONTACT_PROTOCOL.json'),preflight=_file_binding(pre),case=_file_binding(root/'CASE_NATIVE_ENVELOPE.json'),tests=_file_binding(tests),prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),prefix_active_ticks=N,prefix_physics_steps=P,full_ticks=(F-40)//4,dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},budget_proof=dict(native_spent=native,suffix_max=F-P,full_replay_max=F,projected_native_max=native+2*F-P),changed_controller_action_envelope=True,native_model_joint_limits_effort_PD_friction_unchanged=True,original_task_acceptance_unchanged=True,old_halfclosed_control_condition_not_claimed=True,change=case['control_regime']))
    print(dict(prepared=True,full_ticks=(F-40)//4,prefix=P,maximum_native=native+2*F-P),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
