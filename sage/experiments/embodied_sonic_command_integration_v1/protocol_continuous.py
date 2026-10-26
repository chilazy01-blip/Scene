"""Complete transition continuity before running the preserved native contact controller."""
import argparse,time
from pathlib import Path
from .protocol_joint import authorize as previous
from .protocol import read_bound_json,safe_save,_file_binding,check,project_target,spent_steps

def authorize(root):
    p=previous(root);v=read_bound_json(root/'CONTINUOUS_CONTACT_PROTOCOL.json')
    for b in [v['previous_protocol'],v['same_prefix_initial_contact_check'],v['tests'],*v['dependencies'].values()]:check(b)
    return p

def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('approved2hour physics window exhausted')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json');replay=output.name.startswith('continuous_replay')
    if replay:
        charged=output;maximum=ceiling;headroom=0;assert 0<ceiling<=40+4*p['full_ticks']
    else:
        assert output==root/'attempt_24/full' and ceiling==40+4*p['full_ticks']
        charged=output.parent/'cost';maximum=ceiling-p['prefix_physics_steps'];headroom=ceiling
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    spent=spent_steps(ledger)
    assert spent+maximum+headroom<=p['max_new_physics_steps'] and p['prior_native_steps']+spent+maximum+headroom<=75000
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom));safe_save(ledger_root/'COST.json',ledger)

def prepare(root):
    p=previous(root);assert not (root/'CONTINUOUS_CONTACT_PROTOCOL.json').exists()
    restore=root/'CONTACT_RESTORE_CHECK.json';assert read_bound_json(restore)['passed']
    tests=root/'CONTINUOUS_TESTS.xml';assert 'failures="0"' in tests.read_text() and 'errors="0"' in tests.read_text()
    assert not (root/'attempt_23/full').exists()
    names=('task_continuous.py','test_continuous.py','protocol_continuous.py','engine_continuous.py','audit_continuous.py','replay_continuous.py','visualize_continuous.py','render_continuous.py','delivery_continuous.py')
    safe_save(root/'CONTINUOUS_CONTACT_PROTOCOL.json',dict(previous_protocol=_file_binding(root/'CONTACT_TORQUE_PROTOCOL.json'),same_prefix_initial_contact_check=_file_binding(restore),tests=_file_binding(tests),dependencies={n:_file_binding(Path(__file__).with_name(n)) for n in names},change='Before any attempt23 physics, extend the already-proven desired-origin continuity fix to original place/retract paths. Preserve exactly their original transformed cup-world goals, grasp rotation and65/40tick durations. Preplacement behavior and native contact controller are identical and tested, so the exact prefix and initial native LP check are reused. Run attempt24, not an uncorrected23. Original model/PD/friction/task gates and same budget unchanged.',full_ticks=p['full_ticks'],prefix_physics_steps=p['prefix_physics_steps'],maximum_projected_native_steps=75000,new_physics_steps=0))
    print(dict(prepared=True,zero_step_contact_preflight_reused=True,full_ticks=p['full_ticks'],prefix=p['prefix_physics_steps'],maximum_native=75000),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);prepare(ap.parse_args().root)
