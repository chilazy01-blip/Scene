"""Content bindings and fixed, purpose-specific admission requirements.

Receipts are content pins, not signatures or a replacement for trusted evidence.
Only the deterministic assessor can supply this version's supported checks.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath

SCHEMA = 'scene-quality-record/v1'
VERSION = '1.0.0'
STATES = {'pass', 'fail', 'unknown', 'not_applicable'}
STATIC = ('package_binding', 'source_binding', 'coordinates_dimensions',
          'legacy_cavity_binding', 'physical_parameters', 'solver_parameters')
PROFILES = {
    'static_inspection': STATIC,
    'qualified_collection': STATIC + ('contact_fidelity', 'dynamic_release',
                                      'numerical_reliability', 'task_feasibility'),
    'qualified_export': STATIC + ('contact_fidelity', 'dynamic_release',
                                  'numerical_reliability', 'task_feasibility',
                                  'observation_export'),
}


class Rejected(ValueError):
    """A malformed, stale, unsupported or insufficient qualification."""


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate_json_key:' + key)
        result[key] = value
    return result


def loads(data):
    def invalid(value):
        raise Rejected('nonfinite_json:' + value)
    return json.loads(data, object_pairs_hook=_unique, parse_constant=invalid)


def read(path):
    return loads(Path(path).read_bytes())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode()


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 2**20), b''):
            h.update(block)
    return h.hexdigest()


def fingerprint(value):
    return digest_bytes(canonical(value))


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def implementation():
    root = Path(__file__).parent
    return dict(version=VERSION, files={p.name: digest(p) for p in sorted(root.glob('*.py'))})


def relative_name(name):
    p = PurePosixPath(name)
    require(bool(name) and not p.is_absolute() and '..' not in p.parts
            and '\\' not in name and str(p) == name, 'invalid_manifest_path:' + name)
    return name


def finite(value):
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return all(finite(v) for v in value)
    if isinstance(value, (float, int)):
        return math.isfinite(value)
    return True


def metric(state, measurement, units, threshold, evidence, reason, *, applicable=True):
    require(state in STATES, 'invalid_metric_state')
    return dict(state=state, measurement=measurement, units=units,
                threshold=threshold, evidence=evidence, reason=reason,
                applicability=dict(applicable=applicable, explanation=reason))


def qualifications(metrics):
    # Requirements belong to implementation policy, never to a caller-editable list.
    # None of the required checks in these three profiles admits an N/A waiver.
    result = {}
    for purpose, required in PROFILES.items():
        reasons = [name + ':' + metrics.get(name, {}).get('state', 'missing')
                   for name in required if metrics.get(name, {}).get('state') != 'pass']
        result[purpose] = dict(qualified=not reasons, required=list(required), reasons=reasons)
    return result
