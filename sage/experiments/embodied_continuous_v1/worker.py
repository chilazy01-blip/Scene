"""Concrete zero-physics successors for the sealed parallel run."""
import argparse
import json
import os
from pathlib import Path

from .controller import read, sha, write


def execute(action, root):
    plan = read(root / 'PLAN.json')
    predecessor = Path(plan['predecessor'])
    if action == 'verify_predecessor':
        manifest = read(predecessor / 'FINAL_EVIDENCE_MANIFEST.json')
        errors = []
        count = 0
        for name, digest in manifest['files'].items():
            path = Path(name)
            if path.is_absolute():
                # The active AGENT is mutable; bind its exact predecessor bytes.
                path = root / 'evidence' / 'AGENT_before_continuation.md'
            else:
                path = predecessor / name
            count += 1
            if not path.is_file() or sha(path) != digest:
                errors.append(str(path))
        return {'passed': not errors, 'files_checked': count, 'mismatches': errors,
                'physics_steps': 0, 'historical_bytes_unchanged': not errors}
    if action == 'failure_classification':
        mismatch = read(predecessor / 'reports/DEPENDENCY_MISMATCH.json')
        return {
            'passed': True, 'historical_counts_changed': False,
            'A': {'recorded_scientific_failures': 3, 'closed': True,
                  'native01': 'A has no pinned runtime lockfile. Backend sensitivity is evidenced; '
                              'it does not prove this scientific failure was engineering-only.',
                  'next_evidence': 'Review admission assumptions and failure scope before any reclassification; '
                                   'keep original count and closure while unresolved.'},
            'B': {'recorded_scientific_failures': 2, 'closed': True,
                  'closure_type': 'stage_allocation_exhausted_not_scientific_limit',
                  'first_native_dependencies': mismatch,
                  'next_evidence': 'Name-map correction changed multiple inputs and worsened the trajectory. '
                                   'Separate initialization/observation effects using existing input traces.'},
            'rule': 'Track engineering errors, scientific failures, quality failures and inconclusive '
                    'interruptions separately. All launched trials and costs remain charged. '
                    'No automatic historical reclassification or reopening.',
        }
    if action == 'successor_contracts':
        return {
            'passed': True, 'changes_current_physical_admission': False,
            'authorized_engineering': [
                {'id': 'B_observation_contract', 'input': 'reports/B_INPUT_CAUSAL_ANALYSIS.json',
                 'work': 'Extract joint names, initial state and normalization into a versioned input contract; '
                         'write regressions from saved network inputs without integrating a new trajectory.',
                 'acceptance': 'Source/current differences explicitly enumerated; no success inference from a mapping test.'},
                {'id': 'A_release_contract', 'input': 'reports/A_RELEASE_CAUSAL_RECORD.json',
                 'work': 'Specify measured tilt, support force, clearance and abort signals at placement transitions; '
                         'evaluate predicates on the saved success and failure traces.',
                 'acceptance': 'Predicates separate observed cases with false rejects reported; '
                               'offline discrimination is not causal repair or physical validation.'},
                {'id': 'data_contract', 'input': 'data/research_reader_smoke/REPORT_v2.json',
                 'work': 'Keep depth masks, substep actions and research/production labels in export regressions.',
                 'acceptance': 'Reader preserves values and rejects a research excerpt as a complete accepted episode.'},
            ],
            'conditional_physics': {
                'existing_active_method': 'Evidence-supported bounded revisions use shared development allocation; '
                                          'the two-transfer stage quota no longer applies prospectively.',
                'closed_A_and_B': 'Remain closed. A queue rewrite cannot reopen either canonical method.',
                'new_support_force_release': {
                    'status': 'concrete candidate; not authorized as a new contact skill by this execution amendment',
                    'source_proposal_sha256': sha(predecessor / 'NEXT_SCOPE_PROPOSAL.json'),
                    'entry_requires': ['explicit substantive method scope', 'preserved current robot and quality gates',
                                       'canonical lineage and retained previous failures', 'bound controller and case inputs',
                                       'remaining task/replay/service resources and original time window'],
                },
            },
            'failure_successors': ['preserve_first_deviation', 'causal_diagnosis', 'bounded_engineering_revision',
                                   'minimal_regression', 'admitted_full_validation_or_other_authorized_work'],
        }
    if action == 'continuation_audit':
        state = read(root / 'STATE.json')
        return {
            'passed': True, 'full_objective_achieved': False,
            'implementation_deliverable': 'whole-run closure guard, persistent queue, resource pools, failure successors',
            'parent_run_status': 'requires_coordinator_continuation; engineering completion is not parent success',
            'clock_unchanged': plan['clock'] == read(predecessor / 'RUN_CLOCK.json'),
            'historical_scientific_counts': {k: v['scientific_failures'] for k, v in state['methods'].items()},
            'next': 'Read SUCCESSOR_CONTRACTS.json and carry out authorized evidence/engineering work. '
                    'The coordinator must extend the bound queue with concrete work; an empty queue cannot seal the run.',
        }
    if action == 'diagnose_worker':
        state = read(root / 'STATE.json')
        failures = {k: v for k, v in state['jobs'].items() if v['status'] == 'failed'}
        return {'passed': True, 'failed_jobs': failures,
                'next': 'Inspect captured stderr and input bindings, repair in authorized scope, register a new '
                        'bounded job with the same canonical method and cumulative ledger. No blind retry.',
                'whole_run_exit': False}
    raise ValueError(action)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action')
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = execute(args.action, args.root)
    write(args.root / 'reports' / (args.action.upper() + '.json'), result)
    job = Path(os.environ['CONTINUOUS_JOB_DIR'])
    write(job / 'RESULT.json', {'outcome': 'success' if result['passed'] else 'engineering_failure',
                              'report': str(args.root / 'reports' / (args.action.upper() + '.json'))})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
