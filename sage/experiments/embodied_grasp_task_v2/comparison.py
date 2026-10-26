"""Fixed first-20ms comparison; outcomes never cause another physical attempt."""
import gzip
import json
from pathlib import Path
import numpy as np


def load(path):
    with gzip.open(path, 'rt') as f:
        return json.load(f)


def compare(config, output):
    output = Path(output)
    cid = output.name
    prior = Path(config['intervention']['previous_dynamic_stage']) / 'combinations' / cid
    baseline = Path(config['intervention']['source_stage']) / 'combinations' / cid
    c = config['closure_contracts'][cid]
    prefix = {}
    for name in ('hold', 'raise', 'extend', 'lower'):
        with np.load(output / name / 'RAW.npz') as a, np.load(prior / name / 'RAW.npz') as b:
            prefix[name] = {k: float(np.max(abs(a[k]-b[k]))) for k in ('qpos', 'qvel', 'ctrl')}
    assert all(v == 0. for metrics in prefix.values() for v in metrics.values())
    decisions = load(output / 'CLOSURE_DECISIONS.json.gz')
    close = [x for x in decisions if x['phase'] == 'close']
    switched = [x for x in close if x['decision'].get('switched')]
    assert len(switched) == 1
    first = switched[0]
    i = first['before_step'] - 1
    with np.load(output / 'close/RAW.npz') as a, np.load(prior / 'close/RAW.npz') as b:
        before_error = max(float(np.max(abs(a[k][:i+1]-b[k][:i+1]))) for k in ('qpos', 'qvel'))
        assert before_error == 0. and np.array_equal(a['ctrl'][:i], b['ctrl'][:i])
        assert a['ctrl'][i, 5] == a['ctrl'][i-1, 5] == first['previous_reference']
        force_after = float(a['actuator_force'][i+1, 5])
        speed_after = float(a['actuator_velocity'][i+1, 5])
    windows = {}
    for name, root in [('v2', output), ('v1', prior), ('original_closing', baseline)]:
        metrics = load(root / 'close/METRICS.json.gz')[i:i+20]
        with np.load(root / 'close/RAW.npz') as a:
            forces = a['actuator_force'][i+1:i+1+len(metrics), 5]
        rows = []
        for j, (metric, force) in enumerate(zip(metrics, forces)):
            q = metric['contact_quality']
            rows.append(dict(ms_after_switch=j+1, left_N=q['left']['force_N'], right_N=q['right']['force_N'],
                             loaded=min(q['left']['force_N'], q['right']['force_N']) >= c['contact_force_min'],
                             present=min(q['left']['force_N'], q['right']['force_N']) >= c['presence_force_min'],
                             pad_valid=min(q['left']['pad_fraction'], q['right']['pad_fraction']) >= c['min_pad_fraction'],
                             com_valid=q['contact_com_offset_m'] is not None and q['contact_com_offset_m'] <= c['max_com_offset'],
                             native_effort_N=float(force)))
        windows[name] = dict(actual_samples=len(rows), loaded_samples=sum(x['loaded'] for x in rows),
                             all_present=all(x['present'] for x in rows), rows=rows)
    result = json.loads((output / 'EXECUTION_RESULT.json').read_text())
    phase_failure = next((p for p in result['phases'] if p['status'] == 'fail'), None)
    return dict(id=cid, unchanged_approach_steps=13000, approach_errors=prefix,
                first_switch_close_step=i+1, close_prefix_error=before_error,
                switch=dict(velocity=first['observation']['velocity'], applied_reference=first['previous_reference'],
                            reference_force_jump_N=first['decision']['force_change_from_reference_only'],
                            first_actual_poststep_effort_N=force_after, first_poststep_velocity=speed_after),
                first_twenty_ms=windows, required_each_side_N=c['contact_force_min'],
                ready_events=[dict(phase=x['phase'], before_step=x['before_step'], time=x['observation']['time'])
                              for j,x in enumerate(decisions) if x['decision'].get('ready') and
                              (j == 0 or not decisions[j-1]['decision'].get('ready'))],
                final=dict(status=result['status'], physics_steps=result['physics_steps'], closure_state=result['closure_state'],
                           closure_ready=result['closure_ready'], closure_failure=result['closure_failure'],
                           failed_phase=None if phase_failure is None else phase_failure['id'],
                           failures=[] if phase_failure is None else phase_failure['failures']),
                cumulative_attempts=3, interpretation='development-only finite intervention; continuity and confirmation semantics both changed; no independent validation or single-cause success claim')
