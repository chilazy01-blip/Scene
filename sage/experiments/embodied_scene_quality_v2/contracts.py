"""Content pins and explicit finite-case qualification, not a production license."""
from pathlib import Path
from sage.experiments.embodied_scene_quality_v1.contracts import (
    Rejected, require, read, loads, canonical, digest, digest_bytes, fingerprint,
    write_new, metric, finite)

SCHEMA = 'scene-quality-primitives/v2'


def implementation():
    here = Path(__file__).parent
    paths = list(here.glob('*.py')) + list((here.parent/'embodied_scene_quality_v1').glob('*.py'))
    return {str(p): digest(p) for p in sorted(paths)}


def bound(path, expected):
    path = Path(path)
    require(path.is_file(), 'missing_evidence:' + str(path))
    require(digest(path) == expected, 'evidence_changed:' + str(path))
    return path


def reference(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=digest(path), bytes=path.stat().st_size)


def read_ref(ref):
    return read(bound(ref['path'], ref['sha256']))


def load_protocol(path, expected):
    protocol = read(bound(path, expected))
    require(protocol['schema'] == 'scene-quality-primitives-protocol/v2' and finite(protocol), 'protocol_schema_or_finite')
    scope = protocol['scope']; cases = scope['cases']
    require(scope['robot_present'] is False and scope['continuous_range_validated'] is False,
            'unsupported_primitive_scope')
    require(len(cases) > 0 and len({c['key'] for c in cases}) == len(cases), 'duplicate_or_empty_cases')
    require(all(c['expected_response'] in ('stable', 'observe_only') for c in cases), 'invalid_expectation')
    require(protocol['geometry']['recipe'] == 'source_height_columns_in_task_roi/v1', 'unsupported_proxy_recipe')
    require(protocol['geometry']['surface_dilation_m'] == 0, 'unsupported_surface_dilation')
    require(protocol['physics']['base_dt_s'] > 0 and protocol['physics']['refined_dt_s'] > 0
            and protocol['physics']['duration_s'] > 0, 'invalid_time_contract')
    return protocol


def decisions(metrics):
    common = ['input_binding', 'geometry_fidelity', 'dynamic_release', 'numerical_reliability',
              'primitive_task_feasibility']
    profiles = {'candidate_inspection': ['input_binding'], 'isolated_release_cases': common,
                'qualified_collection': common + ['full_robot_task'],
                'qualified_export': common + ['full_robot_task', 'observation_export']}
    result = {}
    for key, needed in profiles.items():
        reasons = [name+':'+metrics.get(name, {}).get('state', 'missing')
                   for name in needed if metrics.get(name, {}).get('state') != 'pass']
        result[key] = dict(qualified=not reasons, required=needed, reasons=reasons)
    return result
