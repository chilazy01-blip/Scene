"""Frozen per-trial evidence under the user's overriding six-hour authorization."""
import time
from pathlib import Path
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import project_target
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save


def check(binding):
    assert _file_binding(Path(binding['path']))==binding,binding['path']


def authorize(root):
    p=read_bound_json(root/'PROTOCOL.json')
    auth=read_bound_json(Path(p['authorization']['path']))
    for b in [p['authorization'],p['case'],p['scene'],p['reference'],p['prefix_report'],p['prefix_trace'],p['prefix_io'],*p['inputs'].values(),*p['dependencies'].values()]:check(b)
    assert auth['previous_step_cap_superseded'] and auth['previous_wall_deadlines_superseded']
    assert auth['deadline_epoch_utc']==p['deadline_epoch_utc']
    return p


def spent_steps(ledger):
    return sum(read_bound_json(Path(x['output'])/'REPORT.json')['physics_steps'] if (Path(x['output'])/'REPORT.json').exists() else x['maximum_steps'] for x in ledger['reservations'])


def reserve(root,output,ceiling):
    p=authorize(root)
    if time.time()>=p['deadline_epoch_utc']:raise RuntimeError('user six-hour window expired')
    ledger_root=Path(p['ledger_root']);ledger=read_bound_json(ledger_root/'COST.json')
    replay=output.name.startswith('continuous_replay')
    charged=output if replay else output.parent/'cost'
    assert not any(x['output']==str(charged) for x in ledger['reservations'])
    assert 0<ceiling<=40+4*p['full_ticks']
    maximum=ceiling if replay else ceiling-p['prefix_physics_steps']
    ledger['reservations'].append(dict(output=str(charged),maximum_steps=maximum,episode_output=str(output),success_replay_headroom=0 if replay else ceiling))
    safe_save(ledger_root/'COST.json',ledger)


def make_task(p,*args):
    import importlib
    return importlib.import_module(p['task_module']).Task(*args)
