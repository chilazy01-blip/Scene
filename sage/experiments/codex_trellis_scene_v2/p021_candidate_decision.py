"""Per-candidate terminal accounting for new P021 protocols; old rounds frozen."""
import argparse
import json
from pathlib import Path


def candidate_decisions(protocol, attempts):
    if protocol.get('schema') != 'p021-candidate-protocol/v2':
        raise ValueError('A versioned candidate protocol is required')
    runs = {row['run_id']: row for row in protocol['runs']}
    if not runs or len(runs) != len(protocol['runs']):
        raise ValueError('Missing or duplicate planned runs')
    records = {row['run_id']: row for row in attempts}
    if len(records) != len(attempts) or records.keys()-runs.keys():
        raise ValueError('Duplicate or unplanned attempts')
    if any(row.get('status') not in ('running', 'completed', 'failed') for row in attempts):
        raise ValueError('Unknown attempt status')
    pending = [rid for rid in runs if records.get(rid, {}).get('status') not in ('completed', 'failed')]
    failures = [rid for rid, row in records.items() if row['status']=='failed']
    decisions = {}
    for method, requirement in protocol['candidate_requirements'].items():
        own = [rid for rid, row in runs.items() if row['method']==method]
        controls = requirement['required_control_run_ids']
        checks = requirement['required_checks']
        if (not own or not controls or not checks or any(rid not in runs for rid in controls)
                or not {'automated_passed','benchmark_passed','AI_visual_passed','coefficient_effect_passed'} <= set(checks)):
            raise ValueError('Candidate requires own cells, explicit controls and complete acceptance checks')
        reasons = []
        for rid in dict.fromkeys([*own, *controls]):
            row = records.get(rid, {})
            if row.get('status') != 'completed':
                reasons.append(rid + ':not_completed')
                continue
            expected = runs[rid]['comparison_signature_sha256']
            if not expected or row.get('comparison_signature_sha256') != expected:
                reasons.append(rid + ':comparison_controls_changed')
            # Control-specific requirements are frozen separately: e.g. B0 does
            # not claim a low/high coefficient effect that it intentionally lacks.
            required = checks if rid in own else requirement['required_control_checks']
            if not required:
                raise ValueError('Control checks must be explicit and nonempty')
            reasons.extend(rid + ':' + check for check in required if row.get(check) is not True)
        eligible = not reasons
        decisions[method] = {'eligible': eligible, 'own_runs': own, 'required_controls': controls,
                             'reasons': reasons, 'selectable': eligible and not pending}
    return {'schema': 'p021-candidate-decision/v2', 'pending': pending, 'execution_failures': failures,
        'all_planned_attempts_terminal': not pending, 'candidates': decisions,
        'selection_ready': not pending and any(row['eligible'] for row in decisions.values()),
        'promoted': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--attempts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = candidate_decisions(json.loads(args.protocol.read_text()), json.loads(args.attempts.read_text()))
    with args.output.open('x') as output:
        json.dump(result, output, indent=2, allow_nan=False)
        output.write('\n')


if __name__ == '__main__':
    main()
