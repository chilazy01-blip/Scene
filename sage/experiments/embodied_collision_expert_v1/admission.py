"""Fail closed on incomplete or rejected prospective task matrices."""


def require_matrix(results, expected_names, expected_ticks):
    names = [row['name'] for row in results]
    if len(names) != len(set(names)):
        raise ValueError('duplicate_matrix_case')
    if set(names) != set(expected_names):
        raise ValueError('incomplete_matrix')
    rejected = []
    for row in results:
        if row.get('physics_steps') != 0 or row.get('policy_forwards') != 0:
            raise ValueError('prospective_static_scope_required')
        if (row.get('passed') is not True or row.get('full_coverage') is not True
                or row.get('ticks') != expected_ticks
                or row.get('expected_ticks') != expected_ticks
                or row.get('static_bad_ticks') != 0
                or row.get('endpoint_rejections')):
            rejected.append(row['name'])
    if rejected:
        raise ValueError('rejected_matrix_cases:' + ','.join(sorted(rejected)))
    return {'static_matrix_complete': True, 'cases': len(results),
            'ticks_per_case': expected_ticks,
            'physical_admitted': False, 'qualified_task_episodes': 0}
