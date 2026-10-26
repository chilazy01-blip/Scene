import fcntl
from pathlib import Path
import time
from .common import ROOT,check,read_bound_json,safe_save,_file_binding
from .guard import load_task
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import project_target


def authorize(root):
    p=read_bound_json(Path(root)/'PROTOCOL.json')
    for key in ('authorization','plan','case','scene','reference','prefix_report','prefix_trace','prefix_io','candidate'):
        check(p[key])
    for b in [*p['inputs'].values(),*p['dependencies'].values()]:check(b)
    auth=read_bound_json(Path(p['authorization']['path']))
    assert auth['user_authorized_expert_code_and_tools']
    assert p['prior_native_steps']==auth['prior_native_steps']==91644
    assert p['max_new_physics_steps']==auth['max_new_physics_steps']==64000
    assert p['deadline_epoch_utc']==auth['deadline_epoch_utc']
    assert p['solver_schedule']=={'activation_step':3960,'noslip_iterations':3}
    assert p['full_ticks']==2800
    return p


def spent_steps(ledger):
    return sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps']
        if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])


def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('expert round physics deadline reached')
    with (ROOT/'COST.lock').open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        ledger=read_bound_json(ROOT/'COST.json');replay=output.name.startswith('continuous_replay')
        charged=output if replay else output.parent/'cost'
        assert not any(x['output']==str(charged) for x in ledger['reservations'])
        assert 0<ceiling<=11240
        maximum=ceiling if replay else ceiling-p['prefix_physics_steps']
        headroom=0 if replay else ceiling
        if spent_steps(ledger)+maximum+headroom>64000:raise RuntimeError('budget insufficient including full success replay')
        ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=headroom))
        safe_save(ROOT/'COST.json',ledger)


def make_task(p,*args):return load_task(p['candidate'],*args)
