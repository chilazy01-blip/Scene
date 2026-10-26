"""Issue and re-evaluate immutable sidecars without changing source packages."""
from __future__ import annotations

from pathlib import Path
import time

from .contracts import (PROFILES, SCHEMA, STATES, Rejected, digest_bytes, finite,
                        fingerprint, implementation, loads, metric, qualifications,
                        require, write_new)
from .inspect import compiled_checks, snapshot, source_bindings, static_checks


def _unknown_metrics():
    explanations = {
        'package_binding': 'Package not yet bound',
        'source_binding': 'Source provenance not yet bound',
        'coordinates_dimensions': 'Coordinates and recorded dimensions not yet reconciled',
        'legacy_cavity_binding': 'Legacy cavity not yet checked',
        'physical_parameters': 'Declared physical priors not yet read back from compiled model',
        'solver_parameters': 'Solver settings not yet read back from compiled model',
        'contact_fidelity': 'No registered source/proxy fidelity tolerances for the declared task range',
        'dynamic_release': 'No versioned, preregistered dynamic range qualification; historical probes are context only',
        'numerical_reliability': 'No registered timestep/replay qualification for this use range',
        'task_feasibility': 'Legacy endpoint/static-load reports are context; no v1 scoped task qualification importer',
        'observation_export': 'No scene-quality-bound observation/export qualification importer',
        'cross_asset_coverage': 'Only this asset combination identified; independent cross-asset coverage unverified',
    }
    result = {key: metric('unknown', None, None,
                         {'source': 'scene-quality/v1 policy', 'rule': 'required evidence not available'},
                         [], reason) for key, reason in explanations.items()}
    return result


def assess(package, sources):
    """Deterministic findings; no integration, resets, rendering, controllers or RNG."""
    require(isinstance(sources, dict) and all(isinstance(k, str) and isinstance(v, str)
            for k, v in sources.items()), 'invalid_source_references')
    require(set(sources) <= {'layout', 'request', 'legacy_endpoints', 'legacy_static_load',
                            'contact_diagnostic_report', 'contact_diagnostic_result'}, 'unsupported_source_reference')
    metrics = _unknown_metrics()
    result = dict(subject=None, scope=None, metrics=metrics, sources={}, qualification={},
                  supported_layout='generator-container-task-package/v1; legacy cavity/v1; named free target',
                  engine=None)
    model = None
    current = 'package_binding'
    try:
        context = snapshot(package)
        files = context['files']; task = context['docs']['task.json']
        result['subject'] = dict(package_manifest_sha256=context['manifest_sha256'],
            model_sha256=files['model.xml'], task_sha256=files['task.json'],
            proxy_sha256=files['container_cuboids.npz'], files=files,
            physical_parameters_sha256=None, solver_parameters_sha256=None)
        result['scope'] = dict(task=task['task'], target_body=task['target_body'],
            container_body=task['container_body'], support_body=task['support_body'],
            target_dimensions_m=task['target_dimensions_m'],
            declared_use='static inspection of the exact bound package; no dynamic range qualification',
            dynamic_range=None, asset_support_combinations=1, independent_validation_combinations=0,
            split=task.get('split', 'unknown'),
            assumptions=['rigid target with explicit uncalibrated mass/bbox inertia/contact priors',
                         'environment fixed to world', 'legacy 5mm cavity proxy'],
            excluded=['physical truth', 'dynamic release range', 'learning utility', 'mass production'])
        metrics['package_binding'] = metric('pass', {'files': len(files)}, 'sha256',
            {'source': 'FILES.json', 'rule': 'all package bytes and XML file references bound'},
            ['FILES.json', 'model.xml', 'task.json'], 'Complete package snapshot matches its manifest')
        current = 'source_binding'
        bindings, documents, source_metric = source_bindings(context, sources)
        result['sources'] = bindings; metrics[current] = source_metric
        # A mismatched source may not reach native model loading.
        if source_metric['state'] == 'fail':
            raise Rejected(source_metric['reason'])
        current = 'legacy_cavity_binding'
        try:
            metrics.update(static_checks(context, documents))
        except Rejected as exc:
            if any(word in str(exc) for word in ('coordinate', 'dimension', 'pose', 'layout_object')):
                current = 'coordinates_dimensions'
            raise
        metrics['environment_articulation'] = metric('not_applicable', None, None,
            {'source': 'declared task scope', 'rule': 'fixed rigid environment; no articulation task'},
            ['model.xml', 'task.json'], 'Articulated furniture operation excluded from this placement task', applicable=False)
        current = 'physical_parameters'
        try:
            compiled, model = compiled_checks(context)
        except Rejected as exc:
            if any(word in str(exc) for word in ('solver', 'timestep', 'action_units')):
                current = 'solver_parameters'
            raise
        metrics.update(compiled)
        result['subject']['physical_parameters_sha256'] = fingerprint(compiled['physical_parameters']['measurement'])
        result['subject']['solver_parameters_sha256'] = fingerprint(compiled['solver_parameters']['measurement'])
        result['engine'] = compiled['solver_parameters']['measurement']['mujoco_version']
        metrics['production_cost'] = metric('unknown', {
            'package_bytes': sum(len(b) for b in context['blobs'].values()),
            'model_geoms': int(model.ngeom), 'proxy_cuboids': len(task['cavity']['bottom_geoms']) + len(task['cavity']['wall_geoms']),
            'qualified_training_episodes_added': 0}, {'size': 'byte', 'runtime': 's'},
            {'source': 'static package accounting', 'rule': 'production throughput and physical runtime not measured'},
            ['FILES.json', 'model.xml'], 'Static complexity recorded; production cost/throughput remains unknown')
    except (Rejected, KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        metrics[current] = metric('fail', None, None,
            {'source': 'scene-quality/v1 deterministic checker', 'rule': 'well-formed supported consistent inputs'},
            [], type(exc).__name__ + ':' + str(exc))
        model = None
    result['qualification'] = qualifications(metrics)
    return result, model


def create_record(package, sources):
    started = time.monotonic()
    findings, _ = assess(package, sources)
    return dict(schema=SCHEMA, implementation=implementation(),
                package=str(Path(package).resolve()), sources=dict(sources),
                assessment=findings, created_at_unix_s=time.time(),
                cost=dict(wall_seconds=time.monotonic()-started, new_physics_steps=0,
                          new_generation=0, new_gpu=0, new_forwards=0, new_training=0,
                          new_collection=0, accounting_scope='record assessment only; service costs in run seal'))


def read_pinned_record(path, expected_sha256):
    data = Path(path).read_bytes()
    require(isinstance(expected_sha256, str) and len(expected_sha256) == 64, 'record_pin_required')
    require(digest_bytes(data) == expected_sha256, 'record_digest_mismatch')
    record = loads(data)
    require(record['schema'] == SCHEMA, 'record_schema_mismatch')
    require(record['implementation'] == implementation(), 'quality_implementation_changed')
    require(finite(record), 'nonfinite_quality_record')
    require(record['cost']['wall_seconds'] >= 0 and all(record['cost'][k] == 0 for k in
            ('new_physics_steps', 'new_generation', 'new_gpu', 'new_forwards', 'new_training', 'new_collection')),
            'invalid_stage1_cost_record')
    for key, m in record['assessment']['metrics'].items():
        require(m['state'] in STATES and m['reason'] and m['threshold']['source']
                and isinstance(m['evidence'], list) and isinstance(m['applicability'], dict), 'invalid_metric:' + key)
        require(m['state'] != 'pass' or bool(m['evidence']), 'passing_metric_without_evidence:' + key)
        require(m['state'] != 'not_applicable' or m['applicability']['applicable'] is False,
                'invalid_not_applicable:' + key)
    require(record['assessment']['qualification'] == qualifications(record['assessment']['metrics']),
            'qualification_policy_mismatch')
    return record


def validate_record(package, record_path, expected_sha256):
    record = read_pinned_record(record_path, expected_sha256)
    findings, model = assess(package, record['sources'])
    require(findings == record['assessment'], 'record_evidence_or_assessment_changed')
    return findings, model


def load_admitted(package, record_path, expected_sha256, *, purpose):
    """Actual preflight loader. Denial returns no model and issues no receipt.

Static inspection ignores unrelated dynamic unknowns. Qualified collection and
export are explicit reserved profiles: v1 lacks their physical evidence importer
and therefore cannot issue those qualifications. No legacy execution is invoked.
"""
    require(purpose in PROFILES, 'unsupported_use:' + purpose)
    record = read_pinned_record(record_path, expected_sha256)
    declared = qualifications(record['assessment']['metrics'])[purpose]
    require(declared['qualified'], 'unqualified_use:' + purpose + ':' + ','.join(declared['reasons']))
    findings, model = validate_record(package, record_path, expected_sha256)
    decision = findings['qualification'][purpose]
    require(decision['qualified'] and model is not None, 'unqualified_current_package:' + purpose)
    receipt = dict(schema='scene-quality-admission/v1', purpose=purpose,
        record_sha256=expected_sha256, implementation=implementation(),
        subject=findings['subject'], scope=findings['scope'], engine=findings['engine'],
        required=decision['required'], source_bindings=findings['sources'],
        admission='passed', new_physics_steps=0)
    return model, receipt


def write_sidecar(package, output, value):
    require(not Path(output).resolve().is_relative_to(Path(package).resolve()),
            'quality_sidecar_must_not_modify_package')
    write_new(output, value)
