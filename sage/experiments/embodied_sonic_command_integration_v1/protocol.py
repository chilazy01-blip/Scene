"""New frozen integration, sharing the existing native budget without resetting it."""
import argparse
from pathlib import Path
import time
import numpy as np
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol_preserved import authorize as previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import check,read_bound_json,safe_save,_file_binding,project_target

def authorize(root):
    p=read_bound_json(root/'INTEGRATION_PROTOCOL.json')
    previous(Path(p['ledger_root']))
    for binding in [p['case'],p['prefix_report'],p['prefix_trace'],p['prefix_io'],p['verification'],*p['dependencies'].values()]:check(binding)
    # An approval must quote an actual new user response. Preparation never
    # creates this file and never interprets an unanswered request as approval.
    approval=root/'APPROVED_TIME_WINDOW.json'
    if approval.exists():
        a=read_bound_json(approval)
        assert a['user_response'] and a['received_epoch_utc']>p['deadline_epoch_utc']
        assert a['cumulative_native_cap']==p['cumulative_native_cap']==75000
        assert a['protocol']==_file_binding(root/'INTEGRATION_PROTOCOL.json')
        assert a['deadline_epoch_utc']>a['received_epoch_utc']
        p=dict(p,deadline_epoch_utc=a['deadline_epoch_utc'])
    return p

def spent_steps(ledger):
    return sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('Previously approved physics time window has expired; fresh user time authorization is required by AGENT.md. No steps reserved.')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json')
    replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0
        assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_18/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps']
    assert p['prior_native_steps']+spent+maximum+headroom<=p['cumulative_native_cap']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom))
    safe_save(ledger_root/'COST.json',ledger)

def prepare(root,ledger_root):
    p=previous(ledger_root);assert not (root/'INTEGRATION_PROTOCOL.json').exists()
    verification=read_bound_json(root/'VERIFICATION.json');assert verification['passed'] and verification['new_physics_steps']==0
    assert read_bound_json(ledger_root/'EQUILIBRIUM_PLAN_CHECK.json')['passed']
    assert read_bound_json(ledger_root/'EQUILIBRIUM_RESTORE_PREVIEW.json')['passed']
    source=ledger_root/'attempt_09/full';trace=read_bound_json(source/'TRACE.json');trace['records']=trace['records'][:980]
    trace['events']=[e for e in trace['events'] if e.get('tick',-1)<980];trace['rejected_command']=None
    trace['checkpoint_continuation']=dict(source_trace=_file_binding(source/'TRACE.json'),prefix_physics_steps=3960,prefix_active_ticks=980,prepared_with_zero_integrations=True)
    folder=root/'equilibrium_prefix';folder.mkdir();safe_save(folder/'TRACE.json',trace)
    io=np.load(source/'POLICY_IO.npz',allow_pickle=False);np.savez_compressed(folder/'POLICY_IO.npz',**{k:io[k][:980] for k in io.files})
    rows=trace['records'];assert all(s['safe'] for row in rows for s in row['substeps'])
    safe_save(folder/'REPORT.json',dict(schema='exact-recorded-safe-prefix/v1',physics_steps=3960,new_physics_steps=0,maximum_saturation_run_ticks=np.max([r['projection']['saturation_run_ticks'] for r in rows],axis=0).tolist(),maximum_target_projection_rad=max(r['projection']['maximum_projection_rad'] for r in rows),projected_ticks=sum(bool(r['projection']['projected_joints']) for r in rows),source_report=_file_binding(source/'REPORT.json'),source_trace=_file_binding(source/'TRACE.json')))
    ledger=read_bound_json(ledger_root/'COST.json');spent=spent_steps(ledger);full=8920
    projected=p['prior_native_steps']+spent+2*full-3960
    assert projected==74996<=75000
    p=dict(p,case=_file_binding(ledger_root/'CASE_EQUILIBRIUM_PREVIEW.json'),ledger_root=str(ledger_root),full_ticks=2220,prefix_active_ticks=980,prefix_physics_steps=3960,prefix_report=_file_binding(folder/'REPORT.json'),prefix_trace=_file_binding(folder/'TRACE.json'),prefix_io=_file_binding(folder/'POLICY_IO.npz'),verification=_file_binding(root/'VERIFICATION.json'),dependencies={f.name:_file_binding(f) for f in Path(__file__).parent.glob('*.py')},budget_proof=dict(actual_native_steps=p['prior_native_steps']+spent,suffix_max=4960,success_replay_max=8920,projected_native_max=projected),active_source='native_mug_task_expert/equilibrium_v1',gr00t_service_connected=False,online_planner_in_control_loop=False)
    safe_save(root/'INTEGRATION_PROTOCOL.json',p)
    print(dict(prepared=True,new_physics_steps=0,budget_proof=p['budget_proof'],time_authorization_expired=time.time()>=p['deadline_epoch_utc']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--ledger-root',type=Path,required=True);args=parser.parse_args();prepare(args.root,args.ledger_root)
