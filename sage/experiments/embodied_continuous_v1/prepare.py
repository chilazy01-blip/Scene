"""Append an execution amendment; never modify the sealed predecessor."""
import argparse
import math
from pathlib import Path
import sys
import time

from .controller import initial_state, read, sha, write


def prepare(predecessor, root, implementation_start):
    predecessor, root = predecessor.resolve(), root.resolve()
    if root == predecessor or root.is_relative_to(predecessor):
        raise ValueError('amendment must be outside the sealed predecessor')
    root.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[3]
    agent = project / 'AGENT.md'
    (root / 'evidence').mkdir()
    (root / 'evidence/AGENT_before_continuation.md').write_bytes(agent.read_bytes())
    resource = read(predecessor / 'RESOURCE_PROPOSAL.json')
    ledger = read(predecessor / 'RESOURCE_LEDGER.json')
    if ledger['active']:
        raise ValueError('predecessor workers still active')
    caps, cumulative, base = resource['new_package_delta_caps'], resource['proposed_cumulative_caps'], resource['baseline']
    limits = {k: min(caps[k], cumulative[k] - base[k]) for k in ledger['delta']}
    limits['service_seconds'] = min(caps['stage_service_seconds'], *[
        cumulative[k] - base[k] for k in ('stage_service_seconds', 'package_service_seconds', 'global_service_seconds')])
    limits['download_bytes'] = resource['source_download_chain_cap_bytes'] - resource['source_download_already_used_bytes']
    overhead = math.ceil(time.time() - implementation_start)
    spent = ledger['delta'] | {'service_seconds': ledger['service_seconds_new'] + overhead,
                               'download_bytes': ledger['download_bytes_new']}
    code = {str(p): sha(p) for p in Path(__file__).parent.glob('*.py')}
    inputs = code | {str(predecessor / name): sha(predecessor / name) for name in [
        'PLAN.json', 'RESOURCE_PROPOSAL.json', 'USER_APPROVAL.json', 'RUN_CLOCK.json',
        'RESOURCE_LEDGER.json', 'CLOSURE.json', 'FINAL_EVIDENCE_MANIFEST.json']}
    plan = {
        'schema': 'embodied-continuous/v1', 'predecessor': str(predecessor),
        'amendment_purpose': 'Implement the user-requested continuation rules; preserve original scientific scope and clock.',
        'working_directory': str(project), 'clock': read(predecessor / 'RUN_CLOCK.json'),
        'implementation_started_epoch': implementation_start, 'max_job_seconds': 900, 'heartbeat_seconds': 30,
        'execution_mode': 'serial bounded workers, at most 4 CPU cores and 5.5 GiB address space each',
        'limits': limits, 'initial_spent': spent, 'inherited_cumulative_base': base,
        'historical_ledger_sha256': sha(predecessor / 'RESOURCE_LEDGER.json'),
        'coordinator_charge': {'seconds': overhead, 'through_epoch': time.time(), 'basis': 'conservative wall time'},
        'protected_pools': {
            'comparison': {'task_attempts': 4, 'task_physics_steps': 960000, 'service_seconds': 7220,
                           'wbc_forwards': 200000, 'render_passes': 20000},
            'holdout': {'task_attempts': 6, 'task_physics_steps': 1440000, 'service_seconds': 10830,
                        'wbc_forwards': 600000, 'render_passes': 900000},
            'export_seal': {'service_seconds': 8200, 'render_passes': 200000},
        },
        'allocation_policy': {
            'development': 'Shared native/transfer/generated development pool; no per-stage attempt cap.',
            'remaining_development_trials_at_import': 20 - ledger['delta']['task_attempts'] - 4 - 6,
            'comparison_and_holdout_never_borrowed': True,
            'method_limit_not_reset_by_stage_edit_rename_or_new_job': True,
            'quality_gates_unchanged': True,
            'allocation_change_does_not_reopen_previously_closed_methods': True,
        },
        'scientific_failure_limit': 3,
        'methods': {b: read(predecessor / 'branches' / b / 'STATE.json') for b in ('A', 'B')},
        'authorized_scopes': ['existing_evidence_analysis', 'reversible_engineering', 'successor_preparation'],
        'scope_boundaries': {
            'allowed': ['dependency and script repair', 'names/units/timing contracts', 'data reader validation',
                        'offline saved-trace diagnosis', 'concrete successor design and minimal engineering regression'],
            'requires_substantive_scope_decision': ['new contact skill or training', 'reopening closed physical methods',
                                                   'robot or quality changes', 'higher hard budgets or resetting the deadline'],
        },
        'stop_policy': ['verified objective', 'user stop', 'original deadline',
                        'actual global resource exhaustion', 'evidenced external blocker covering all authorized alternatives'],
        'not_stop_reasons': ['branch closed', 'stage quota', 'worker timeout', 'dependency error', 'empty queue', 'report written'],
        'jobs': {},
    }
    disk = read(predecessor / 'evidence/DISK_BASELINE.json')
    plan['disk_checks'] = [
        {'name': k, 'roots': roots + [str(Path(__file__).parent)], 'cap_bytes': cumulative[k]}
        for k, roots in disk['roots'].items()
    ] + [{'name': 'new_package', 'roots': [str(predecessor), str(root), str(Path(__file__).parent)],
          'cap_bytes': caps['stage_disk_bytes']}]
    actions = ['verify_predecessor', 'failure_classification', 'successor_contracts', 'continuation_audit', 'diagnose_worker']
    for index, action in enumerate(actions):
        job = {
            'kind': 'planning' if action == 'diagnose_worker' else 'analysis',
            'scope': 'existing_evidence_analysis', 'pool': 'development', 'timeout_seconds': 180 if index == 0 else 30,
            'reservation': {'service_seconds': 185 if index == 0 else 35}, 'disk_reservation_bytes': 2 * 1024**2,
            'inputs': inputs, 'argv': [sys.executable, '-B', '-m', 'sage.experiments.embodied_continuous_v1.worker', action, str(root)],
            'initial': index == 0, 'on_failure': ['diagnose_worker'] if action != 'diagnose_worker' else [],
            'on_success': [actions[index + 1]] if index < 3 else [],
        }
        plan['jobs'][action] = job
    write(root / 'PLAN.json', plan)
    write(root / 'AUTHORIZATION.json', {
        'approved': True, 'user_instruction': '那就去落实这些要求',
        'scope': 'Implement continuation policy, dynamic development allocation, recovery and tests. '
                 'Existing physics closure, scientific limits, quality gates and original clock retained.',
        'prior_resource_approval': str(predecessor / 'USER_APPROVAL.json'),
        'plan_sha256': sha(root / 'PLAN.json'), 'bindings': inputs, 'epoch': time.time(),
    })
    write(root / 'STATE.json', initial_state(plan))
    write(root / 'ACCOUNTING.json', {'physics_steps_new': 0, 'training_updates_new': 0,
                                    'preparation_coordinator_seconds': overhead,
                                    'charged_to_existing_package': True, 'clock_reset': False})
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('predecessor', type=Path)
    parser.add_argument('root', type=Path)
    parser.add_argument('--implementation-start', type=float, required=True)
    args = parser.parse_args()
    print(prepare(args.predecessor, args.root, args.implementation_start))


if __name__ == '__main__':
    main()
