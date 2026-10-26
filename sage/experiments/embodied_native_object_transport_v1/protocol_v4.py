"""New finite round: original physical plant, task-first legal action projection."""

import argparse
from pathlib import Path
import time
import numpy as np
from .protocol_v3 import authorize as authorize_parent
from .report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def check(binding):
    if sha256_file(Path(binding['path'])) != binding['sha256']:
        raise ValueError('frozen dependency changed: ' + binding['path'])


def authorize(root):
    p = read_bound_json(root / 'PROTOCOL.json')
    assert p['schema'] == 'native-mug-task-first-round/v4'
    for b in [p['parent_protocol'], p['handoff_snapshot'], *p['dependencies'].values(),
              p['case'], p['scene'], p['reference'], p['admission'], *p['inputs'].values()]:
        check(b)
    authorize_parent(Path(p['parent_root']))
    return p


def reserve(root, output, ceiling):
    p = authorize(root)
    if time.time() >= p['deadline_epoch_utc']:
        raise RuntimeError('new finite round deadline reached')
    assert output in [root / 'version_04/full', root / 'version_05/full', root / 'continuous_replay']
    ledger = read_bound_json(root / 'COST.json')
    assert not any(r['output'] == str(output) for r in ledger['reservations'])
    charged = 0
    for r in ledger['reservations']:
        report = Path(r['output']) / 'REPORT.json'
        charged += read_bound_json(report)['physics_steps'] if report.exists() else r['maximum_steps']
    if charged + ceiling > p['max_new_physics_steps'] or p['prior_native_steps'] + charged + ceiling > p['cumulative_native_cap']:
        raise RuntimeError('new finite round physics budget exhausted')
    ledger['reservations'].append(dict(output=str(output), maximum_steps=ceiling,
                                     reserved_at_epoch_utc=time.time()))
    safe_save(root / 'COST.json', ledger)


def project_target(target, previous, lower, upper, max_step):
    candidate = np.asarray(target)
    previous = np.asarray(previous)
    if not np.isfinite(candidate).all() or not np.isfinite(previous).all():
        raise ValueError('nonfinite target')
    projected = np.clip(candidate, lower, upper)
    correction = float(np.max(np.abs(projected - candidate)))
    delta = float(np.max(np.abs(projected - previous)))
    if delta > max_step:
        raise ValueError('original target slew rejected')
    return projected, dict(maximum_projection_rad=correction, maximum_step_rad=delta,
                          projected_joints=np.flatnonzero(projected != candidate).tolist())


def freeze(root, parent):
    assert not (root / 'PROTOCOL.json').exists()
    old = authorize_parent(parent)
    root.mkdir(parents=True, exist_ok=True)
    handoff = root / 'HANDOFF_BEFORE.md'
    assert not handoff.exists()
    handoff.write_bytes((Path(__file__).parents[3] / 'AGENT.md').read_bytes())
    p = dict(old)
    p.update(schema='native-mug-task-first-round/v4', parent_root=str(parent),
             parent_protocol=_file_binding(parent / 'VERSION_03_PROTOCOL.json'),
             handoff_snapshot=_file_binding(handoff),
             user_resume_verbatim='读取 /data/wsj/main/scene/AGENT.md，按最新断点继续推进。',
             policy_basis='2026-10-22 latest handoff: stable task completion; finite raw targets clip to real ranges and record, no raw 2degree rejection',
             start_epoch_utc=time.time(), deadline_epoch_utc=time.time()+7200,
             max_new_physics_steps=30000, prior_native_steps=25147, cumulative_native_cap=60000,
             max_causal_versions=2, version_outputs=['version_04/full', 'version_05/full'],
             admission=_file_binding(parent / 'version_01/admission/REPORT.json'),
             admission_prefix_policy='same initial100 ticks must match original qpos/qvel/warmstart bitwise; no new warmup qualification run',
             small_target_excess_rule='finite target clipped to unchanged real jnt_range; original slew gate retained; action history uses actually projected commands',
             saturation_policy='record every raw/mixed/legal target, consecutive saturation counts and >=1s warning; no raw excess or saturation-only failure; terminate measured physical failure, original stage timeout or round ceiling',
             failure_policy='save every executed state and refused command; no fabricated later phases; ordinary failed grasp must be reported and handled only by a valid recovery path',
             scope='same full G1, native furniture and triangle mesh mug; no training/download/install/commit/delegation; no external supports/forces/teleportation',
             bottleneck='premature command-layer abort prevents observing stable native pickup/carry/place',
             reusable_deliverable='auditable legal action adapter plus real complete-or-failed native trajectory and MP4',
             exit_conditions='at most2 cause-driven versions, stop on success or budget/deadline or repeated unresolved physical failure; replay only independently qualified full task',
             dependencies={n: _file_binding(Path(__file__).with_name(n)) for n in
                           ('protocol_v4.py', 'engine_v4.py', 'audit_v4.py', 'visualize_v4.py', 'test_projection_v4.py')})
    safe_save(root / 'PROTOCOL.json', p)
    safe_save(root / 'COST.json', dict(reservations=[], max_physics_steps=30000,
                                    prior_native_steps=25147, cumulative_cap=60000))
    print(dict(frozen=True, deadline_epoch_utc=p['deadline_epoch_utc'], physics_steps=0), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--parent', type=Path, required=True)
    a = ap.parse_args()
    freeze(a.root, a.parent)
