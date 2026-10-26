"""Higher bandwidth native contact-reference feedback, same physical and task limits."""
import argparse,time
from pathlib import Path
from .protocol_continuous import authorize as previous
from .protocol import read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'FAST_CONTACT_PROTOCOL.json')
    for b in [v['previous_protocol'],v['cause'],v['preflight'],v['tests'],*v['dependencies'].values()]:check(b)
    return dict(p,full_ticks=v['full_ticks'])

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0;assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_25/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'FAST_CONTACT_PROTOCOL.json').exists()
    pre=root/'FAST_CONTACT_PREFLIGHT.json';assert read_bound_json(pre)['passed']
    tests=root/'FAST_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    ledger=read_bound_json(Path(p['ledger_root'])/'COST.json');native=p['prior_native_steps']+spent_steps(ledger);P=p['prefix_physics_steps'];F=((75000-native+P)//8)*4
    assert native==65068 and P==5244 and F==7588
    names=('task_fast.py','test_fast.py','protocol_fast.py','engine_fast.py','audit_fast.py','replay_fast.py','visualize_fast.py','render_fast.py','delivery_fast.py')
    safe_save(root/'FAST_CONTACT_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'CONTINUOUS_CONTACT_PROTOCOL.json'),cause=_file_binding(root/'CONTACT_TRACKING_RATE_CAUSE.json'),preflight=_file_binding(pre),tests=_file_binding(tests),dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},full_ticks=(F-40)//4,budget_proof=dict(native_spent=native,suffix_max=F-P,full_replay_max=F,projected_native_max=native+2*F-P),change='Same actual6D contact allocation, loaded normal minima and continuous body/placement references. Increase only the contact-reference torque-error integral gain from2/s to10/s and use the same original symmetric.006rad/20ms reference slew. Native motor PD/effort/friction/halfclosed limits and every original task/replay gate unchanged.'))
    print(dict(prepared=True,full_ticks=(F-40)//4,maximum_native=native+2*F-P),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
