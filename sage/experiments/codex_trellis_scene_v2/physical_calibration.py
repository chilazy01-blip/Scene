"""Analyze source-bound measurements without replacing simulation defaults.

Mass repeatability and horizontal sliding friction require separate records.
These estimates do not identify a contact solver's compliance or damping.
"""
from pathlib import Path
import hashlib
import json
import math
import statistics


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Expected finite numeric measurement')
    return float(value)


def _summary(values):
    if len(values) < 3:
        raise ValueError('At least three independent trials are required')
    spread = statistics.stdev(values)
    return dict(trials=len(values), mean=statistics.mean(values), minimum=min(values),
                maximum=max(values), sample_standard_deviation=spread,
                repeatability_standard_error=spread / math.sqrt(len(values)),
                uncertainty_scope='repeatability only; systematic instrument/model errors are not included')


def _evidence(binding, directory):
    path = Path(binding['path'])
    if not path.is_absolute():
        path = directory / path
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != binding['sha256']:
        raise ValueError('Measurement evidence SHA-256 mismatch: ' + str(path))
    return dict(path=str(path.resolve()), sha256=digest)


def analyze(path):
    """Validate a completed collection bundle; empty templates remain pending."""
    path = Path(path)
    document = json.loads(path.read_text())
    if document.get('schema') != 'scene-physical-measurements/v1':
        raise ValueError('Unsupported measurement schema')
    if document.get('source_kind') != 'human_physical_measurement':
        raise ValueError('Simulation, inferred and synthetic values cannot be labeled measured')
    for field in ('collector', 'collected_at', 'instrument', 'instrument_calibration_record'):
        if not isinstance(document.get(field), str) or not document[field].strip():
            raise ValueError('Missing measurement provenance: ' + field)
    source = _evidence(document['asset_source'], path.parent)
    evidence = [_evidence(b, path.parent) for b in document.get('raw_evidence', [])]
    if not evidence:
        raise ValueError('Raw measurement evidence is required')
    results = []
    for record in document.get('records', []):
        kind = record['kind']
        if kind == 'mass':
            factor = {'kg': 1., 'g': .001}.get(record.get('unit'))
            if factor is None:
                raise ValueError('Mass units must be kg or g')
            values = [_finite(v) * factor for v in record['trials']]
            if any(v <= 0 for v in values):
                raise ValueError('Mass must be positive')
            resolution = _finite(record['instrument_resolution']) * factor
            if resolution <= 0:
                raise ValueError('Instrument resolution must be positive')
            results.append(dict(kind=kind, object_id=record['object_id'], unit='kg',
                                instrument_resolution=resolution, **_summary(values)))
        elif kind == 'horizontal_sliding_friction':
            assumptions = record.get('assumptions', {})
            required = ('released_no_applied_force', 'translation_without_rolling',
                        'constant_normal_load', 'same_contact_material_pair')
            if not all(assumptions.get(k) is True for k in required):
                raise ValueError('Sliding-friction experiment assumptions are incomplete')
            if abs(_finite(record['measured_plane_tilt_deg'])) > .1:
                raise ValueError('Horizontal approximation requires measured tilt within 0.1 degrees')
            if len(record.get('contact_pair', [])) != 2:
                raise ValueError('Name both contacting materials')
            gravity = _finite(record['gravity_m_s2'])
            if not 9.7 <= gravity <= 9.9:
                raise ValueError('Invalid terrestrial gravity for this collection protocol')
            estimates, fits = [], []
            for trial in record['trials']:
                times = [_finite(v) for v in trial['time_s']]
                speeds = [_finite(v) for v in trial['speed_m_s']]
                if len(times) != len(speeds) or len(times) < 5:
                    raise ValueError('Each sliding trial requires at least five paired samples')
                if any(b <= a for a, b in zip(times, times[1:])) or times[-1] - times[0] < .1:
                    raise ValueError('Sample times must increase across at least 0.1 seconds')
                if any(v <= 0 for v in speeds):
                    raise ValueError('Use only the moving segment, excluding static/reversed samples')
                mt, mv = statistics.mean(times), statistics.mean(speeds)
                slope = sum((t-mt)*(v-mv) for t,v in zip(times,speeds)) / sum((t-mt)**2 for t in times)
                if slope >= 0:
                    raise ValueError('Released horizontal slider must decelerate')
                mu = -slope / gravity
                residual = math.sqrt(sum((v-(mv+slope*(t-mt)))**2 for t,v in zip(times,speeds)) / len(times))
                estimates.append(mu)
                fits.append(dict(deceleration_m_s2=-slope, mu=mu, speed_fit_rmse_m_s=residual))
            results.append(dict(kind=kind, contact_pair=record['contact_pair'], unit='dimensionless',
                                model='Coulomb kinetic friction on a measured horizontal sliding segment',
                                fits=fits, **_summary(estimates)))
        else:
            raise ValueError('Unsupported physical measurement kind: ' + str(kind))
    if not results:
        raise ValueError('No measurements supplied; collection remains pending')
    return dict(schema='scene-physical-calibration-analysis/v1', measurement_source=source,
                input=dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
                raw_evidence=evidence, source_attested_by=document['collector'], results=results,
                independent_provenance_verified=False, simulation_defaults_changed=False,
                contact_compliance_identified=False, inertia_and_center_of_mass_measured=False)
