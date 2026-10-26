"""One authority for dispatch, reservations, recovery and whole-run closure.

Stage counts are telemetry. Scientific limits apply to canonical method IDs.
An empty queue asks the coordinator to plan; it never proves global exhaustion.
Only the standard library is imported, including before admission checks.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time


class AdmissionError(RuntimeError):
    pass


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def evidence_ok(evidence):
    return bool(evidence) and all(
        Path(p).is_file() and sha(p) == digest for p, digest in evidence.items())


def vector(values, keys):
    if set(values) - set(keys):
        raise AdmissionError('unknown resource counter')
    for value in values.values():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
            raise AdmissionError('resource counters must be finite and nonnegative')
    return {key: values.get(key, 0) for key in keys}


def validate_plan(plan):
    limits = vector(plan['limits'], plan['limits'])
    vector(plan['initial_spent'], limits)
    if any(plan['initial_spent'].get(k, 0) > cap for k, cap in limits.items()):
        raise AdmissionError('baseline exceeds package or cumulative cap')
    clock = plan['clock']
    if not clock['start_epoch'] < clock['stop_new_work_epoch'] <= clock['deadline_epoch']:
        raise AdmissionError('invalid immutable clock')
    if plan['max_job_seconds'] > 900 or plan['max_job_seconds'] <= 0:
        raise AdmissionError('unbounded worker')
    if not 0 < plan['heartbeat_seconds'] <= 60:
        raise AdmissionError('heartbeat must be at most 60 seconds')
    for pool in plan['protected_pools'].values():
        vector(pool, limits)
    for key, job in plan['jobs'].items():
        if not key.replace('_', '').isalnum():
            raise AdmissionError('invalid job id')
        cost = vector(job['reservation'], limits)
        if not 0 < job['timeout_seconds'] <= plan['max_job_seconds']:
            raise AdmissionError('unbounded job')
        if cost['service_seconds'] < job['timeout_seconds'] + 5:
            raise AdmissionError('worker time is not fully reserved')
        if not job.get('on_failure') and job['kind'] != 'planning':
            raise AdmissionError('missing failure successor: ' + key)
        if job['pool'] not in {'development', *plan['protected_pools']}:
            raise AdmissionError('unknown budget pool')
        if job['kind'] not in {'analysis', 'engineering', 'planning', 'physics', 'audit', 'diagnostic', 'export', 'seal'}:
            raise AdmissionError('unknown job kind')
        for successor in job.get('on_failure', []) + job.get('on_success', []) + job.get('requires', []):
            if successor not in plan['jobs'] or successor == key:
                raise AdmissionError('missing or recursive successor')
        if not job.get('inputs') or not job.get('argv'):
            raise AdmissionError('unbound execution entry')
        if job['kind'] in {'audit', 'diagnostic'} and cost.get('task_attempts', 0):
            raise AdmissionError('audit/diagnostic cannot reserve a new task')
        if job['kind'] not in {'physics', 'audit', 'diagnostic'} and any(
                cost.get(k, 0) for k in ['task_attempts', 'task_physics_steps', 'diagnostic_physics_steps']):
            raise AdmissionError('physical work disguised as engineering')


def initial_state(plan):
    validate_plan(plan)
    return {
        'status': 'active', 'objective_verified': None, 'user_stop': None,
        'external_blocker': None, 'spent': vector(plan['initial_spent'], plan['limits']),
        'pool_spent': {k: vector({}, plan['limits']) for k in plan['protected_pools']},
        'methods': copy.deepcopy(plan['methods']), 'active': None,
        'jobs': {key: {'status': 'pending' if job.get('initial') else 'dormant'}
                 for key, job in plan['jobs'].items()},
        'stage_counts': {}, 'events': [], 'additional_jobs': {}, 'heartbeat_epoch': time.time(),
    }


def remaining(plan, state):
    reserve = state['active']['reservation'] if state['active'] else {}
    return {key: cap - state['spent'][key] - reserve.get(key, 0) for key, cap in plan['limits'].items()}


def job_blockers(plan, state, key, now):
    job = plan['jobs'][key]
    blockers = []
    if any(state['jobs'][dep]['status'] != 'succeeded' for dep in job.get('requires', [])):
        blockers.append('prerequisite')
    deadline = plan['clock']['deadline_epoch'] if job['kind'] == 'seal' else plan['clock']['stop_new_work_epoch']
    if now + job['timeout_seconds'] + 5 > deadline:
        blockers.append('time_window')
    if job['scope'] not in plan['authorized_scopes']:
        blockers.append('scope_not_authorized')
    if not evidence_ok(job['inputs']):
        blockers.append('input_binding_changed')
    if job['kind'] == 'audit':
        replay = job.get('replay', {})
        if not (replay.get('exact_saved_inputs') is True
                and evidence_ok(replay.get('bindings'))
                and set(replay.get('bindings', {})) <= set(job['inputs'])
                and replay.get('source_method') in state['methods']):
            blockers.append('saved_replay_binding_missing')
    if job['kind'] == 'diagnostic':
        diagnostic = job.get('diagnostic', {})
        if not (diagnostic.get('bounded_contact_window') is True
                and 0 < diagnostic.get('max_sim_seconds', 0) <= 10
                and evidence_ok(diagnostic.get('saved_state'))
                and job['reservation'].get('diagnostic_physics_steps', 0) > 0
                and job['reservation'].get('task_physics_steps', 0) == 0):
            blockers.append('bounded_diagnostic_contract_missing')
        if job.get('method') not in state['methods'] or state['methods'][job['method']]['closed']:
            blockers.append('method_closed')
    if job['kind'] == 'physics':
        method = state['methods'].get(job.get('method'))
        if method is None or method['closed'] or method['scientific_failures'] >= plan['scientific_failure_limit']:
            blockers.append('method_closed')
        if not evidence_ok(job.get('admission')):
            blockers.append('physical_admission_missing')
        else:
            contract = read(next(iter(job['admission'])))
            if not (contract.get('admitted') is True and contract.get('method') == job.get('method')
                    and contract.get('scope') == job['scope'] and contract.get('quality_gates_preserved') is True
                    and contract.get('inputs') == job['inputs']):
                blockers.append('physical_contract_mismatch')
            if job['pool'] in {'comparison', 'holdout'} and not contract.get('controller_frozen'):
                blockers.append('controller_not_frozen')
            if job['pool'] == 'holdout' and not (contract.get('production_admitted') and contract.get('fresh_cases')):
                blockers.append('production_admission_missing')
        if job['reservation'].get('task_attempts', 0) < 1:
            blockers.append('physical_trial_unreserved')
    # Never reserve the same protected pool twice, nor borrow another pool.
    for resource, cap in plan['limits'].items():
        protected = sum(max(0, reserve.get(resource, 0) - state['pool_spent'][pool][resource])
                        for pool, reserve in plan['protected_pools'].items() if pool != job['pool'])
        if state['spent'][resource] + job['reservation'].get(resource, 0) + protected > cap:
            blockers.append('budget:' + resource)
        if job['pool'] in plan['protected_pools'] and resource in plan['protected_pools'][job['pool']]:
            allowance = plan['protected_pools'][job['pool']].get(resource, 0)
            if state['pool_spent'][job['pool']][resource] + job['reservation'].get(resource, 0) > allowance:
                blockers.append('pool_budget:' + resource)
    return sorted(set(blockers))


def decide(plan, state, now):
    report = {'epoch': now, 'remaining': remaining(plan, state), 'blockers': {},
              'method_status': state['methods'], 'objective_achieved': False}
    if state['status'] == 'closed':
        return report | {'action': 'closed', 'reason': state['closure']['reason']}
    # A running worker must be reconciled before closure, even on hard exits.
    if state['active'] is not None:
        reason = 'worker_active'
        if now >= plan['clock']['deadline_epoch'] or evidence_ok(state['user_stop']):
            reason = 'cancel_and_reconcile'
        return report | {'action': 'await_worker', 'reason': reason}
    if evidence_ok(state['user_stop']):
        return report | {'action': 'stop', 'reason': 'user_stop'}
    if evidence_ok(state['objective_verified']):
        objective = read(next(iter(state['objective_verified'])))
        if objective.get('full_objective_achieved') is True and objective.get('independent_acceptance_passed') is True:
            return report | {'action': 'stop', 'reason': 'objective_verified', 'objective_achieved': True}
    if now >= plan['clock']['deadline_epoch']:
        return report | {'action': 'stop', 'reason': 'deadline'}
    for key, value in state['jobs'].items():
        if value['status'] != 'pending':
            continue
        blockers = job_blockers(plan, state, key, now)
        report['blockers'][key] = blockers
        if not blockers:
            return report | {'action': 'dispatch', 'job': key, 'reason': 'authorized_work_available'}
    # Only a resource shared by ALL work can prove global resource exhaustion.
    # Exhausted physics steps/trials do not prevent zero-physics analysis.
    if remaining(plan, state)['service_seconds'] <= 0:
        return report | {'action': 'stop', 'reason': 'service_budget_exhausted'}
    blocker = state['external_blocker']
    if blocker and evidence_ok(blocker.get('evidence')):
        pending = {k for k, v in state['jobs'].items() if v['status'] in {'pending', 'dormant'}}
        if (blocker.get('external') is True and blocker.get('requires_user_or_external_change') is True
                and blocker.get('authorized_alternatives_exhausted') is True
                and set(blocker.get('covers_jobs', [])) == pending):
            return report | {'action': 'stop', 'reason': 'verified_external_blocker'}
    if now >= plan['clock']['stop_new_work_epoch']:
        return report | {'action': 'seal_window', 'reason': 'prepare_evidence_until_deadline'}
    return report | {'action': 'replan', 'reason': 'queue_requires_coordinator_work_not_global_exit'}


def record_result(plan, state, key, outcome, usage, evidence, now):
    if outcome not in {'success', 'engineering_failure', 'scientific_failure', 'timeout', 'interrupted'}:
        raise AdmissionError('unknown outcome')
    job = plan['jobs'][key]
    if outcome == 'scientific_failure' and job['kind'] != 'physics':
        raise AdmissionError('engineering job cannot consume scientific failure count')
    usage = vector(usage, plan['limits'])
    if job['kind'] == 'physics' and usage.get('task_physics_steps', 0) > 0 and usage.get('task_attempts', 0) != 1:
        raise AdmissionError('integrated task must consume exactly one task attempt')
    if job['kind'] in {'audit', 'diagnostic'} and usage.get('task_attempts', 0):
        raise AdmissionError('replay/diagnostic task count must be zero')
    # Validate the complete vector before mutating any counter.
    if any(amount > job['reservation'].get(resource, 0) for resource, amount in usage.items()):
        raise AdmissionError('usage exceeds reservation')
    for resource, amount in usage.items():
        if amount > job['reservation'].get(resource, 0):
            raise AdmissionError('usage exceeds reservation: ' + resource)
        state['spent'][resource] += amount
        if job['pool'] in state['pool_spent']:
            state['pool_spent'][job['pool']][resource] += amount
    if outcome == 'scientific_failure':
        method = state['methods'][job['method']]
        method['scientific_failures'] += 1
        if method['scientific_failures'] >= plan['scientific_failure_limit'] or job['pool'] == 'holdout':
            method['closed'] = True
            method['closure_reason'] = 'scientific_limit' if job['pool'] != 'holdout' else 'production_first_failure'
    state['jobs'][key] = {'status': 'succeeded' if outcome == 'success' else 'failed',
                          'outcome': outcome, 'usage': usage, 'evidence': evidence, 'finished_epoch': now}
    stage = job.get('stage', job['kind'])
    state['stage_counts'][stage] = state['stage_counts'].get(stage, 0) + usage.get('task_attempts', 0)
    activated = []
    for successor in job.get('on_success' if outcome == 'success' else 'on_failure', []):
        if state['jobs'][successor]['status'] == 'dormant':
            state['jobs'][successor]['status'] = 'pending'
            activated.append(successor)
    state['active'] = None
    state['heartbeat_epoch'] = now
    state['events'].append({'epoch': now, 'job': key, 'outcome': outcome, 'activated': activated,
                            'spent_after': dict(state['spent'])})


@contextmanager
def locked(root):
    root = Path(root)
    with (root / 'CONTROLLER.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan = read(root / 'PLAN.json')
        auth = read(root / 'AUTHORIZATION.json')
        if not auth.get('approved') or auth.get('plan_sha256') != sha(root / 'PLAN.json'):
            raise AdmissionError('plan authority mismatch')
        if not evidence_ok(auth['bindings']):
            raise AdmissionError('predecessor or implementation binding changed')
        state = read(root / 'STATE.json')
        plan['jobs'].update(state.get('additional_jobs', {}))
        validate_plan(plan)
        yield plan, state


def extend_jobs(root, additions, reason):
    """Register bounded successors without resetting time, costs or method status."""
    if not reason.strip() or not additions:
        raise AdmissionError('concrete successor reason and jobs required')
    with locked(root) as (plan, state):
        if state['status'] == 'closed':
            raise AdmissionError('cannot reopen a closed run')
        if set(additions) & set(plan['jobs']):
            raise AdmissionError('cannot rewrite an old attempt')
        for job in additions.values():
            if job['scope'] not in plan['authorized_scopes'] or not evidence_ok(job.get('inputs')):
                raise AdmissionError('successor scope or input binding missing')
        plan['jobs'].update(additions)
        validate_plan(plan)
        state.setdefault('additional_jobs', {}).update(additions)
        state['jobs'].update({k: {'status': 'pending' if j.get('initial') else 'dormant'} for k, j in additions.items()})
        state['events'].append({'epoch': time.time(), 'action': 'extend_queue', 'reason': reason, 'jobs': list(additions)})
        write(Path(root) / 'STATE.json', state)
        return decide(plan, state, time.time())


def inspect(root):
    with locked(root) as (plan, state):
        report = decide(plan, state, time.time())
        write(Path(root) / 'CONTINUATION_CHECK.json', report)
        return report


def close(root, reason):
    """The sole closure writer; caller cannot supply its own stop decision."""
    with locked(root) as (plan, state):
        report = decide(plan, state, time.time())
        if report['action'] != 'stop' or report['reason'] != reason:
            write(Path(root) / 'REJECTED_CLOSURE.json', report | {'requested_reason': reason})
            raise AdmissionError('whole-run closure rejected: ' + report['reason'])
        state.update(status='closed', closure=report)
        write(Path(root) / 'STATE.json', state)
        write(Path(root) / 'CLOSURE.json', report)
        return report


def disk_admission(plan, root, job):
    for item in plan.get('disk_checks', []):
        raw = subprocess.check_output(['du', '-s', '-B1', *item['roots']], text=True, timeout=30)
        used = sum(int(line.split()[0]) for line in raw.splitlines())
        if used + job.get('disk_reservation_bytes', 0) > item['cap_bytes']:
            raise AdmissionError('disk budget: ' + item['name'])
    stat = os.statvfs(root)
    if stat.f_bavail * stat.f_frsize < job.get('disk_reservation_bytes', 0):
        raise AdmissionError('disk free space')


def child_limits():
    import resource
    cpus = sorted(os.sched_getaffinity(0))[:4]
    os.sched_setaffinity(0, cpus)
    memory = int(11 * 1024**3)
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def measured_usage(work, job, elapsed, process_ok):
    """Only a completed, request-bound receipt can release unused reservations.

    Partial counters are useful evidence but cannot exclude work since the last
    flush. Missing/crashed/invalid receipts therefore charge full reservations.
    """
    charged = dict(job['reservation'])
    charged['service_seconds'] = min(elapsed, charged['service_seconds'])
    path = Path(work) / 'USAGE_FINAL.json'
    if not path.exists() or not process_ok:
        return charged, 'conservative_reservation'
    try:
        receipt = read(path)
        actual = vector(receipt['usage'], job['reservation'])
        if (receipt.get('complete') is not True or
                receipt.get('request_sha256') != sha(Path(work) / 'REQUEST.json') or
                any(v > job['reservation'].get(k, 0) for k, v in actual.items())):
            return charged, 'invalid_receipt_conservative_reservation'
        actual['service_seconds'] = charged['service_seconds']
        return actual, 'request_bound_actual_usage'
    except (ValueError, KeyError, AdmissionError, OSError):
        return charged, 'invalid_receipt_conservative_reservation'


def recover(root):
    """No blind resubmission after coordinator interruption; timeout owns children."""
    with locked(root) as (plan, state):
        active = state['active']
        if active is None:
            return False
        if time.time() <= active['deadline_epoch'] + 5:
            return False
        key = active['job']
        # A missing receipt costs the full reservation, including physics.
        record_result(plan, state, key, 'interrupted', plan['jobs'][key]['reservation'],
                      {'recovery': 'expired bounded worker; full reservation charged'}, time.time())
        write(Path(root) / 'STATE.json', state)
        return True


def run_one(root):
    root = Path(root).resolve()
    recover(root)
    with locked(root) as (plan, state):
        report = decide(plan, state, time.time())
        write(root / 'CONTINUATION_CHECK.json', report)
        if report['action'] != 'dispatch':
            return report
        key = report['job']
        job = plan['jobs'][key]
        try:
            disk_admission(plan, root, job)
        except (AdmissionError, subprocess.SubprocessError, OSError) as exc:
            record_result(plan, state, key, 'engineering_failure', {}, {'disk_preflight': str(exc)}, time.time())
            write(root / 'STATE.json', state)
            return decide(plan, state, time.time())
        work = root / 'jobs' / key
        work.mkdir(parents=True, exist_ok=False)
        started = time.time()
        state['active'] = {'job': key, 'started_epoch': started,
                           'deadline_epoch': started + job['timeout_seconds'], 'reservation': job['reservation']}
        state['jobs'][key]['status'] = 'running'
        write(work / 'REQUEST.json', job)
        write(root / 'STATE.json', state)
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
               MKL_NUM_THREADS='1', CUDA_VISIBLE_DEVICES='', CONTINUOUS_JOB_DIR=str(work))
    outcome = 'engineering_failure'
    detail = {}
    with (work / 'stdout.log').open('w') as stdout, (work / 'stderr.log').open('w') as stderr:
        try:
            # timeout survives a coordinator crash and kills the complete worker group.
            proc = subprocess.Popen(['timeout', '--signal=KILL', str(job['timeout_seconds']), *job['argv']],
                                    cwd=plan['working_directory'], env=env, stdout=stdout, stderr=stderr,
                                    start_new_session=True, preexec_fn=child_limits)
            last_heartbeat = 0
            while proc.poll() is None:
                now = time.time()
                if now - last_heartbeat >= plan['heartbeat_seconds']:
                    with locked(root) as (_, state):
                        state['heartbeat_epoch'] = now
                        state['active']['pid'] = proc.pid
                        write(root / 'STATE.json', state)
                        cancel = evidence_ok(state['user_stop']) or now >= plan['clock']['deadline_epoch']
                    last_heartbeat = now
                    if cancel:
                        os.killpg(proc.pid, signal.SIGKILL)
                time.sleep(0.05)
            elapsed = time.time() - started
            # Remove surviving descendants even when the main command exits normally.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            detail = {'returncode': proc.returncode, 'elapsed_seconds': elapsed}
            outcome = 'success' if proc.returncode == 0 else ('timeout' if proc.returncode in {-9, 124, 137} else 'engineering_failure')
        except Exception as exc:
            elapsed = time.time() - started
            detail = {'exception': repr(exc), 'elapsed_seconds': elapsed}
    # Physical workers must provide a bound result; never infer task success from exit 0.
    usage, accounting = measured_usage(work, job, elapsed, outcome == 'success')
    detail['accounting'] = accounting
    result = work / 'RESULT.json'
    if result.exists():
        detail['result_sha256'] = sha(result)
        result_value = read(result)
        if outcome == 'success':
            outcome = result_value.get('outcome', 'engineering_failure')
    elif job['kind'] in {'physics', 'audit', 'diagnostic'}:
        outcome = 'engineering_failure'
    with locked(root) as (plan, state):
        if state['active'] is None or state['active']['job'] != key:
            raise AdmissionError('worker reconciliation already changed')
        if outcome not in {'success', 'engineering_failure', 'scientific_failure', 'timeout', 'interrupted'}:
            outcome = 'engineering_failure'
        if outcome == 'scientific_failure' and job['kind'] != 'physics':
            outcome = 'engineering_failure'
        record_result(plan, state, key, outcome, usage, detail, time.time())
        write(work / 'RECEIPT.json', state['jobs'][key])
        write(root / 'STATE.json', state)
        report = decide(plan, state, time.time())
        write(root / 'CONTINUATION_CHECK.json', report)
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['inspect', 'step', 'run', 'close', 'recover', 'extend'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--reason')
    parser.add_argument('--jobs', type=Path)
    args = parser.parse_args()
    if args.command == 'extend':
        result = extend_jobs(args.root, read(args.jobs), args.reason or '')
    elif args.command == 'close':
        result = close(args.root, args.reason)
    elif args.command == 'recover':
        result = {'recovered': recover(args.root)}
    elif args.command in {'step', 'run'}:
        result = run_one(args.root)
        while args.command == 'run' and result['action'] == 'dispatch':
            result = run_one(args.root)
    else:
        result = inspect(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # 75 means the coordinator must continue planning, NOT a closed experiment.
    return 75 if result.get('action') == 'replan' else 0


if __name__ == '__main__':
    raise SystemExit(main())
