"""Exact frozen matrix coverage; geometry never implies native task admission."""
def require_geometry_matrix(cases, results):
    names = [r['name'] for r in results]
    expected = [c['name'] for c in cases]
    if len(names) != len(set(names)) or set(names) != set(expected):
        raise ValueError('missing_or_duplicate_case')
    for result in results:
        if (not result['passed'] or not result['full_coverage'] or result['ticks'] != 5200
                or result['physics_steps'] != 0 or result['policy_forwards'] != 0
                or len(result['stage_results']) != 15
                or len({r['stage'] for r in result['stage_results']}) != 15
                or not all(r['passed'] and r['ticks'] == 150 and r['endpoint_error_m'] <= .006
                           for r in result['stage_results'])):
            raise ValueError('incomplete_or_failed_case:'+result['name'])
    return dict(geometry_matrix_passed=True,physical_admitted=False,
                native_command_coverage=False,training_episode_qualified=False)
