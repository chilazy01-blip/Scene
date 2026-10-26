"""Evaluate saved failure evidence; no simulator, inference or control imports."""
import os
from pathlib import Path
import sys

from .controller import read, sha, write


def linf(left, right):
    if len(left) != len(right):
        raise ValueError('action shape mismatch')
    return max(abs(x - y) for x, y in zip(left, right))


def main():
    root = Path(sys.argv[1])
    predecessor = Path(read(root / 'PLAN.json')['predecessor'])
    paths = {key: predecessor / name for key, name in {
        'B': 'reports/B_INPUT_CAUSAL_ANALYSIS.json',
        'A': 'reports/A_RELEASE_CAUSAL_RECORD.json',
        'data': 'data/research_reader_smoke/REPORT_v2.json',
    }.items()}
    b_rows = []
    for record in read(paths['B'])['records']:
        action = {k: v[0] for k, v in record['counterfactual_actions'].items()}
        b_rows.append({
            'tick': record['policy_tick'],
            'native_recorded_vs_saved_recompute_linf': linf(action['native'], record['recorded_native_action'][0]),
            'target_recorded_vs_saved_recompute_linf': linf(action['target'], record['recorded_target_action'][0]),
            'proprio_change_native_rgb_linf': linf(action['native'], action['target_proprio_native_rgb']),
            'proprio_change_target_rgb_linf': linf(action['native_proprio_target_rgb'], action['target']),
            'rgb_change_native_proprio_linf': linf(action['native'], action['native_proprio_target_rgb']),
            'rgb_change_target_proprio_linf': linf(action['target_proprio_native_rgb'], action['target']),
            'interaction_linf': max(abs(t - pn - nr + n) for t, pn, nr, n in zip(
                action['target'], action['target_proprio_native_rgb'], action['native_proprio_target_rgb'], action['native'])),
        })
    a_rows = []
    for case, record in read(paths['A'])['readonly_regression'].items():
        a_rows.append({'case': case, 'observed_task_passed': record['task_passed'],
                       'touchdown_tilt_deg': record['touchdown_tilt_deg'],
                       'tilt_within_existing_25deg_envelope': record['touchdown_tilt_deg'] <= 25,
                       'COM_within_contact_hull': record['COM_within_contact_hull'],
                       'existing_combined_candidate_allows_release': record['would_allow_release_with_existing25deg_gate']})
    data = read(paths['data'])
    tests = {
        'B_saved_network_recompute_matches_recorded': all(
            row['native_recorded_vs_saved_recompute_linf'] == row['target_recorded_vs_saved_recompute_linf'] == 0 for row in b_rows),
        'A_tilt_envelope_separates_only_the_two_observed_cases': all(
            row['observed_task_passed'] == row['tilt_within_existing_25deg_envelope'] for row in a_rows),
        'A_combined_hull_rule_has_a_known_false_reject': any(
            row['observed_task_passed'] and not row['existing_combined_candidate_allows_release'] for row in a_rows),
        'data_numeric_RGB_readback_provenance_zero_error': data['passed'] and all(
            value == 0 for value in data['numeric_rgb_max_errors'].values()),
        'depth_clip_mask_has_actual_readback_evidence': data['depth_validity_revision']['checked_by_actual_sidecar_read'],
        'research_excerpt_not_accepted_as_production': data['production_accepted'] is False,
    }
    report = {
        'passed': all(tests.values()), 'checks': tests, 'B_input_factor_comparison': b_rows,
        'A_candidate_predicate_regression': a_rows,
        'evidence': {str(p): sha(p) for p in paths.values()},
        'physics_steps_new': 0, 'policy_forwards_new': 0, 'training_updates_new': 0,
        'A_conclusion': 'The tilt envelope distinguishes this pair; the combined static support-hull rule '
                        'also rejects the native success. Neither is a validated seating recovery or a production gate.',
        'B_conclusion': 'The 2x2 saved input crossovers quantify state/RGB effects and their interaction '
                        'at recorded ticks. They do not prove that a mapping fix completes the physical task.',
        'data_scope': 'Provenance contract check of the existing eight-row reader result; not a new reader run or new episode.',
        'physical_methods_reopened': False, 'full_objective_achieved': False,
    }
    destination = root / 'reports/OFFLINE_CONTRACT_REGRESSION.json'
    write(destination, report)
    write(Path(os.environ['CONTINUOUS_JOB_DIR']) / 'RESULT.json', {
        'outcome': 'success' if report['passed'] else 'engineering_failure', 'report': str(destination),
        'report_sha256': sha(destination)})
    print({key: value for key, value in tests.items()})
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
