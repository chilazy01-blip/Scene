"""Validate the handoff and start its engineering phase without resetting history.

`check` never authorizes or starts a run. `start` requires a user-approval receipt
bound to the prepared files; it does not grant physical admission to C or D.
"""
import argparse
from contextlib import contextmanager
import copy
import fcntl
import os
from pathlib import Path
import sys
import time

from sage.experiments.embodied_continuous_v1 import controller as c


@contextmanager
def package_lock(prepared):
    with (Path(prepared) / 'START.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def check(prepared, recovering_owner=None):
    prepared = Path(prepared).resolve()
    plan = c.read(prepared / 'PLAN.json')
    proposal = c.read(prepared / 'RESOURCE_PROPOSAL.json')
    request = c.read(prepared / 'APPROVAL_REQUEST.json')
    contract = c.read(prepared / 'STARTUP_CONTRACT.json')
    if plan['human_plan_sha256'] != c.sha(plan['human_plan_path']):
        raise c.AdmissionError('human plan changed')
    if plan['resource_proposal_sha256'] != c.sha(prepared / 'RESOURCE_PROPOSAL.json'):
        raise c.AdmissionError('resource proposal changed')
    if request['plan_sha256'] != c.sha(prepared / 'PLAN.json') or request['resource_proposal_sha256'] != c.sha(prepared / 'RESOURCE_PROPOSAL.json'):
        raise c.AdmissionError('decision bindings changed')
    if plan['startup_contract_sha256'] != c.sha(prepared / 'STARTUP_CONTRACT.json'):
        raise c.AdmissionError('startup contract changed')
    if not c.evidence_ok(contract['code_bindings']):
        raise c.AdmissionError('entry or scheduler implementation changed')
    if (plan['clock_proposal']['duration_seconds'] != 43200
            or plan['clock_proposal']['seal_reserve_seconds'] != 1800):
        raise c.AdmissionError('twelve-hour window or seal reserve changed')
    source = Path(contract['source_root'])
    state = c.read(source / 'STATE.json')
    if state['active'] is not None:
        raise c.AdmissionError('predecessor worker still active')
    if state['methods'] != plan['inherited_methods']:
        raise c.AdmissionError('method lineage changed')
    old_caps = c.read(source / 'PLAN.json')['limits']
    if old_caps != proposal['package_caps_before']:
        raise c.AdmissionError('predecessor resource caps changed')
    proposed_caps = proposal['package_caps_proposed']
    changed = {k for k in old_caps if old_caps[k] != proposed_caps[k]}
    if changed != {'task_attempts'} or proposed_caps['task_attempts'] != 26:
        raise c.AdmissionError('unexpected hard-cap change')
    if proposal['project_task_cap_proposed'] != 62 or proposal['additional_development_trials'] != 6:
        raise c.AdmissionError('task increment mismatch')
    if proposal['allocation'] != {'development_shared': 8, 'frozen_comparison': 4, 'fresh_holdouts': 6}:
        raise c.AdmissionError('task pool mismatch')
    if plan['task_allocation'] != proposal['allocation'] or sum(proposal['allocation'].values()) != 18:
        raise c.AdmissionError('plan/allocation mismatch')
    spent = c.vector(state['spent'], proposed_caps)
    caps = {}
    for key, allowance in proposal['remaining_allocation'].items():
        if spent[key] < proposal['baseline_spent'][key]:
            raise c.AdmissionError('cumulative counter decreased: ' + key)
        if spent[key] + allowance > proposed_caps[key]:
            raise c.AdmissionError('remaining package cannot cover successor: ' + key)
        caps[key] = spent[key] + allowance
    if sum(proposal['service_allocation'].values()) != proposal['remaining_allocation']['service_seconds']:
        raise c.AdmissionError('service allocations do not sum')
    if proposal['service_allocation']['execute_and_independent_replay'] < 18 * 2 * 905:
        raise c.AdmissionError('worker cleanup overhead omitted')
    if proposal['remaining_allocation']['task_physics_steps'] < 18 * 300 / .0025 * 2 + 240000:
        raise c.AdmissionError('independent replay not fully reserved')
    render = contract['render_contract']
    if sum(render.values()) != proposal['remaining_allocation']['render_passes'] or render['six_fresh_full_episodes'] < 180000:
        raise c.AdmissionError('RGB-D coverage inconsistent with render cap')
    source_auth = c.read(source / 'AUTHORIZATION.json')
    if source_auth.get('plan_sha256') != c.sha(source / 'PLAN.json'):
        raise c.AdmissionError('predecessor authority binding changed')
    if source_auth.get('bindings') and not c.evidence_ok(source_auth['bindings']):
        raise c.AdmissionError('predecessor evidence or implementation changed')
    if not source_auth.get('approved') and (recovering_owner is None or source_auth.get('authority_transferred_to') != recovering_owner):
        raise c.AdmissionError('predecessor execution authority already transferred')
    return plan, proposal, contract, state, caps


def compile_runtime(prepared, destination, start_epoch, checked=None):
    """Pure compilation; this function does not authorize, write or launch anything."""
    prepared, destination = Path(prepared).resolve(), Path(destination).resolve()
    plan, proposal, contract, source_state, caps = checked or check(prepared)
    duration = plan['clock_proposal']['duration_seconds']
    reserve = plan['clock_proposal']['seal_reserve_seconds']
    methods = copy.deepcopy(plan['inherited_methods'])
    for name, spec in plan['methods_proposed'].items():
        methods[name] = {'closed': False, 'scientific_failures': 0, 'physical_admission': False,
                         'proposal': spec, 'historical_methods': ['A', 'B']}
    clock = {'start_epoch': start_epoch, 'deadline_epoch': start_epoch + duration,
             'stop_new_work_epoch': start_epoch + duration - reserve,
             'includes_all_implementation': True, 'reset_on_resume': False}
    bindings = contract['code_bindings'] | {
        str(prepared / name): c.sha(prepared / name)
        for name in ['PLAN.json', 'RESOURCE_PROPOSAL.json', 'STARTUP_CONTRACT.json']}
    runtime = {
        'working_directory': contract['working_directory'], 'clock': clock,
        'max_job_seconds': 900, 'heartbeat_seconds': 30, 'limits': caps,
        'initial_spent': source_state['spent'], 'methods': methods, 'scientific_failure_limit': 3,
        'authorized_scopes': ['reversible_engineering', 'existing_evidence_analysis', 'successor_preparation',
                              'contact_recovery_research', 'object_pose_planning_research'],
        'protected_pools': {
            'comparison': {'task_attempts': 4, 'task_physics_steps': 960000, 'service_seconds': 7240,
                           'wbc_forwards': 400000, 'render_passes': 8000},
            'holdout': {'task_attempts': 6, 'task_physics_steps': 1440000, 'service_seconds': 10860,
                        'wbc_forwards': 600000, 'render_passes': 180000},
            'export_seal': {'service_seconds': 6000, 'render_passes': 30000},
        },
        'jobs': {}, 'prepared_plan': str(prepared / 'PLAN.json'),
        'inherited_cumulative_base': proposal['inherited_cumulative_base'],
        'inherited_old_clock': plan['clock_proposal']['old_clock_unchanged'],
        'startup_contract': contract, 'execution_mode': 'serial engineering bootstrap; physics requires new admission',
        'disk_checks': copy.deepcopy(contract.get('disk_checks', [])),
    }
    for item in runtime['disk_checks']:
        if item['name'] == 'new_package':
            item['roots'] = list(dict.fromkeys(item['roots'] + [str(destination)]))
    runtime['disk_checks'].append({'name': 'successor_disk', 'roots': [str(destination)],
                                  'cap_bytes': proposal.get('disk_reservation_bytes', 64 * 1024**3)})
    for name, action, initial in [('bootstrap', 'worklist', True), ('bootstrap_diagnosis', 'diagnose', False)]:
        runtime['jobs'][name] = {
            'kind': 'planning', 'scope': 'reversible_engineering', 'pool': 'development',
            'timeout_seconds': 30, 'reservation': {'service_seconds': 35},
            'inputs': bindings, 'argv': [sys.executable, '-B', '-m',
                                       'sage.experiments.embodied_contact_recovery_v1.entry', action, str(destination)],
            'initial': initial, 'on_failure': ['bootstrap_diagnosis'] if initial else [], 'on_success': [],
        }
    c.validate_plan(runtime)
    state = c.initial_state(runtime)
    if c.decide(runtime, state, start_epoch)['action'] != 'dispatch':
        raise c.AdmissionError('prepared engineering entry cannot dispatch')
    return runtime


def approval_check(prepared, approval):
    receipt = c.read(approval)
    required = {'new_method_scope', 'six_additional_development_trials', 'new_twelve_hour_window'}
    if not (receipt.get('approved') is True and receipt.get('user_instruction', '').strip()
            and receipt.get('plan_sha256') == c.sha(prepared / 'PLAN.json')
            and receipt.get('resource_proposal_sha256') == c.sha(prepared / 'RESOURCE_PROPOSAL.json')
            and set(receipt.get('decisions', [])) == required):
        raise c.AdmissionError('explicit bound launch approval required')
    return receipt


def start(prepared, destination, approval):
    invoked_epoch = time.time()
    prepared, destination, approval = map(lambda p: Path(p).resolve(), (prepared, destination, approval))
    if destination == prepared or destination.parent != prepared.parent:
        raise c.AdmissionError('run directory must be separate from the prepared evidence')
    with package_lock(prepared):
        approval_check(prepared, approval)
        # Resuming the same run never reinitializes its ledger, methods or clock.
        if (destination / 'STARTED.json').exists():
            auth = c.read(destination / 'AUTHORIZATION.json')
            if auth.get('prepared_root') != str(prepared) or auth.get('user_approval_sha256') != c.sha(approval):
                raise c.AdmissionError('existing run authority mismatch')
            c.inspect(destination)
            source = Path(c.read(prepared / 'STARTUP_CONTRACT.json')['source_root'])
            if c.read(source / 'AUTHORIZATION.json').get('authority_transferred_to') != str(destination):
                raise c.AdmissionError('predecessor ownership mismatch')
            return {'started': False, 'resumed': True, 'clock': c.read(destination / 'RUN_CLOCK.json')}
        claim = prepared / 'RUN_CLAIM.json'
        if claim.exists() and c.read(claim)['destination'] != str(destination):
            raise c.AdmissionError('this package already belongs to another run')
        checked = check(prepared, recovering_owner=str(destination))
        source = Path(checked[2]['source_root'])
        # Exclude predecessor dispatch while taking and transferring its budget.
        with (source / 'CONTROLLER.lock').open('a') as source_lock:
            fcntl.flock(source_lock, fcntl.LOCK_EX)
            checked = check(prepared, recovering_owner=str(destination))
            if (destination / 'STATE.json').exists():
                partial = c.read(destination / 'STATE.json')
                if partial['events'] or partial['active'] is not None:
                    raise c.AdmissionError('partial initialization has work to reconcile; do not reset it')
            if destination.exists() and not (destination / 'RUN_CLOCK.json').exists():
                raise c.AdmissionError('destination is not an interrupted initialization')
            destination.mkdir(parents=True, exist_ok=True)
            clock_path = destination / 'RUN_CLOCK.json'
            start_epoch = c.read(clock_path)['start_epoch'] if clock_path.exists() else invoked_epoch
            runtime = compile_runtime(prepared, destination, start_epoch, checked)
            if not clock_path.exists():
                c.write(clock_path, runtime['clock'])
            c.write(claim, {'destination': str(destination), 'start_epoch': start_epoch})
            for name in ['STATE.json', 'AUTHORIZATION.json', 'PLAN.json']:
                path = destination / 'evidence' / ('SOURCE_' + name)
                if not path.exists():
                    c.write(path, c.read(source / name))
            c.write(destination / 'PLAN.json', runtime)
            auth = {'approved': True, 'prepared_root': str(prepared),
                    'plan_sha256': c.sha(destination / 'PLAN.json'), 'user_approval_sha256': c.sha(approval),
                    'bindings': runtime['jobs']['bootstrap']['inputs'] | {str(approval): c.sha(approval)}}
            c.write(destination / 'AUTHORIZATION.json', auth)
            c.write(destination / 'STATE.json', c.initial_state(runtime))
            c.write(source / 'AUTHORIZATION.json', c.read(source / 'AUTHORIZATION.json') | {
                'approved': False, 'authority_transferred_to': str(destination), 'transfer_epoch': time.time()})
            c.write(destination / 'STARTED.json', {'started_epoch': start_epoch,
                    'predecessor_retired': True, 'physics_admitted': False, 'objective_achieved': False})
    return {'started': True, 'resumed': False, 'clock': runtime['clock'],
            'next': 'Run bootstrap, then implement/verify the startup worklist in this same long-running turn.'}


def worklist(root, diagnose=False):
    root = Path(root)
    plan = c.read(root / 'PLAN.json')
    result = {'outcome': 'success', 'physics_steps': 0, 'full_objective_achieved': False,
              'requires_coordinator_work': True,
              'next': plan['startup_contract']['before_first_physics'],
              'same_turn_continuation': 'replan/exit75 means implement and append bounded jobs; do not end the long run'}
    if diagnose:
        result['failed_jobs'] = {k: v for k, v in c.read(root / 'STATE.json')['jobs'].items() if v['status'] == 'failed'}
    c.write(Path(os.environ['CONTINUOUS_JOB_DIR']) / 'RESULT.json', result)
    c.write(root / ('BOOTSTRAP_DIAGNOSIS.json' if diagnose else 'STARTUP_WORKLIST.json'), result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['check', 'start', 'worklist', 'diagnose'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--approval', type=Path)
    args = parser.parse_args()
    if args.command == 'check':
        checked = check(args.root)
        compile_runtime(args.root, args.root.parent / 'dry_run_not_created', time.time(), checked)
        result = {'passed': True, 'engineering_entry_ready': True, 'physics_admitted': False,
                  'approval_recorded': False, 'clock_started': False,
                  'current_spent': checked[3]['spent'], 'effective_caps_if_launched': checked[4]}
    elif args.command == 'start':
        if args.output is None or args.approval is None:
            parser.error('start requires --output and --approval')
        result = start(args.root, args.output, args.approval)
    else:
        result = worklist(args.root, args.command == 'diagnose')
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
