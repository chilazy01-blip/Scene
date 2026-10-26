"""Bind generated assets, placement intent and exact model evidence before use.

No controller, data collection, physics state or step is created here. Existing
v1/v2 assessors own scientific requirements; this module cannot relax them.
"""
from pathlib import Path

from sage.experiments.embodied_scene_quality_v1 import quality as static
from sage.experiments.embodied_scene_quality_v1.contracts import (
    Rejected, digest, finite, fingerprint, read, require, write_new)
from sage.experiments.embodied_scene_quality_v2 import evidence as primitive
from sage.experiments.embodied_scene_quality_v2.contracts import (
    bound, decisions, read_ref, reference)

SCHEMA = 'generator-task-intake/v1'
USES = ('candidate_inspection', 'isolated_release_cases',
        'qualified_collection', 'qualified_export')


def implementation():
    return {p.name: digest(p) for p in sorted(Path(__file__).parent.glob('*.py'))}


def validate_intent(intent, task, task_sha256, model, scope):
    """Intent is caller-pinned, never inferred from a favorable outcome."""
    require(isinstance(intent, dict) and finite(intent), 'invalid_intent')
    require(set(intent) == {'schema', 'task_sha256', 'roles', 'placement', 'model', 'scope'},
            'intent_fields')
    require(intent['schema'] == 'asset-task-intent/v1', 'intent_schema')
    require(intent['task_sha256'] == task_sha256, 'intent_task_mismatch')
    roles = {role: task[role + '_semantic_id'] for role in ('target', 'container', 'support')}
    require(intent['roles'] == roles, 'intent_role_mismatch')
    require(intent['placement'] == dict(goal_m=task['goal'], quaternion_wxyz=task['target_quat']),
            'intent_placement_mismatch')
    require(intent['model'] == model, 'intent_model_mismatch')
    require(intent['scope'] == scope, 'intent_scope_mismatch')


def unknown_scope(task):
    return dict(kind='unverified_task_scope', task=task['task'], split=task['split'],
                domain='No release range or full robot task qualified for this exact model')


def describe_roles(task, manifest, sources):
    objects = {item['semantic_id']: item for item in manifest['objects']}
    assets = {item['object_id']: item for item in manifest['asset_resolution']}
    result = {}
    for role in ('target', 'container', 'support'):
        name = task[role + '_semantic_id']
        obj, asset = objects[name], assets[name]
        require(obj['body'] == task[role + '_body'], 'role_body_mismatch:' + role)
        result[role] = dict(semantic_id=name, body=obj['body'], category=obj['category'],
            source_asset=sources['asset:' + name], asset_id=asset['asset_id'],
            dimensions_m=obj['actual_dimensions_m'], pose_z_up=obj['pose_z_up'],
            source_package_collider=obj['collider'], physical_prior=dict(
                mass_kg=obj['mass_kg'], inertia_origin=obj['inertia_origin'],
                friction=obj['friction'], measured=obj['measured']))
    return result


def downstream_requirements(qualifications):
    """An ordered map of evidence gaps, not an automatically scheduled queue."""
    out = []
    for use in ('isolated_release_cases', 'qualified_collection', 'qualified_export'):
        row = qualifications[use]
        out.append(dict(use=use, qualified=row['qualified'], reasons=row['reasons'],
                        action='No execution scheduled; supply bound evidence for each required metric'))
    out.append(dict(use='learning_effect_comparison', qualified=False,
        reasons=['learning_input_numerics:unknown', 'repeatable_development_baseline:unknown',
                 'independent_evaluation_protocol:unknown'],
        action='Separate input numerical checks and baseline admission required; this module cannot authorize training'))
    return out


def prepare_task(generator_output, package, static_record, intent, primitive_record=None):
    """Consume a completed generator output and its adapted package.

    static_record: {path, sha256}; primitive_record: optional {root, path, sha256}.
    A valid failed/unknown candidate can be registered. Registration grants no
    collection rights. open_task rechecks everything before returning a model.
    """
    generator_output, package = Path(generator_output).resolve(), Path(package).resolve()
    findings, _ = static.validate_record(package, static_record['path'], static_record['sha256'])
    require(findings['qualification']['static_inspection']['qualified'], 'static_intake_rejected')
    task = read(bound(package/'task.json', findings['subject']['task_sha256']))
    manifest = read(bound(package/'scene_manifest.json', findings['subject']['files']['scene_manifest.json']))
    require(task['task'] == 'place_in_container', 'unsupported_task')
    require(Path(findings['sources']['layout']['path']).resolve() == generator_output/'layout_plan_final.json',
            'generator_layout_mismatch')
    require(Path(findings['sources']['assembled_glb']['path']).resolve() == generator_output/'scene_codex_trellis_v2.glb',
            'generator_glb_mismatch')
    summary_ref = reference(generator_output/'run_summary.json')
    require(read_ref(summary_ref).get('profile_complete') is True, 'generator_incomplete')
    roles = describe_roles(task, manifest, findings['sources'])
    model = dict(kind='source_package', format='mjcf', sha256=findings['subject']['files']['model.xml'])
    scope = unknown_scope(task)
    unknowns = ('geometry_fidelity', 'dynamic_release', 'numerical_reliability',
                'primitive_task_feasibility', 'full_robot_task', 'observation_export', 'cross_asset_coverage')
    metrics = {name: dict(state='unknown', reason='No exact-model scoped evidence imported') for name in unknowns}
    metrics['input_binding'] = dict(state='pass', reason='Current generated output and static package verified')
    current_model = dict(model, path=str(package/'model.xml'), robot_present=True,
        physical_parameters=findings['metrics']['physical_parameters']['measurement'],
        collider_origin='Source package; see per-role collider descriptions')
    evidence = None
    if primitive_record is not None:
        saved = read_ref(primitive_record)
        actual = primitive.assess(primitive_record['root'], saved['protocol_sha256'], saved['bundle_sha256'])
        require(actual == saved, 'primitive_record_assessment_changed')
        protocol, bundle, binding, _ = primitive.load_binding(
            primitive_record['root'], saved['protocol_sha256'], saved['bundle_sha256'])
        require(Path(protocol['source_package']).resolve() == package, 'primitive_package_mismatch')
        require(saved['subject']['source_task_sha256'] == findings['subject']['task_sha256'],
                'primitive_task_mismatch')
        desc = binding['variants']['candidate']
        model = dict(kind='primitive_candidate', format='mjb', sha256=desc['binary']['sha256'])
        scope = saved['scope']
        metrics = {name: dict(state=item['state'], reason=item['reason']) for name, item in saved['metrics'].items()}
        # Preserve the exact candidate parameters, not the original proxy label.
        physical = desc['description']
        current_model = dict(model, path=desc['binary']['path'], robot_present=False,
            physical_parameters={name: physical[name] for name in ('mass_kg', 'target_inertia',
                'target_ipos', 'target_iquat', 'gravity_m_s2', 'solver', 'contact_settings')},
            material_measured=task['material_measured'],
            collider_origin=protocol['geometry'], model_ngeom=physical['model_ngeom'])
        evidence = dict(root=str(Path(primitive_record['root']).resolve()),
            path=str(Path(primitive_record['path']).resolve()), sha256=primitive_record['sha256'],
            protocol_sha256=saved['protocol_sha256'], bundle_sha256=saved['bundle_sha256'])
    validate_intent(intent, task, findings['subject']['task_sha256'], model, scope)
    qualifications = decisions(metrics)
    identity = dict(task_sha256=findings['subject']['task_sha256'], model=model,
        scope_sha256=fingerprint(scope), roles=roles, placement=intent['placement'],
        physical_parameters=current_model['physical_parameters'],
        generator=dict(layout=findings['sources']['layout'], glb=findings['sources']['assembled_glb'],
                       request=findings['sources']['request'], summary=summary_ref),
        source_group=manifest.get('source_asset_group'), layout_family=manifest.get('layout_family'),
        split=task['split'])
    return dict(schema=SCHEMA, implementation=implementation(),
        inputs=dict(generator_output=str(generator_output), package=str(package),
                    static_record=dict(path=str(Path(static_record['path']).resolve()), sha256=static_record['sha256']),
                    intent=intent, primitive_record=evidence),
        combination_id=fingerprint(identity), identity=identity, current_model=current_model,
        joint_support=dict(target_lower_surface=dict(role='target', representation=roles['target']['source_package_collider']),
            supporting_surface=dict(role='container', source_certificate_sha256=findings['subject']['files']['container_certificate.json']),
            relation='target lower collision surface on container bottom in the explicitly bound placement',
            dynamic_state=metrics['dynamic_release']['state'],
            diagnostic_support_polygon_is_not_an_admission_gate=True),
        metrics=metrics, qualification=qualifications,
        downstream=downstream_requirements(qualifications),
        limits=dict(registration_is_not_production_admission=True, legacy_collectors_migrated=False,
                    continuous_range_validated=False, physical_truth_calibrated=False,
                    new_physics_steps=0, qualified_training_episodes_added=0))


def revalidate_task(path, pin):
    saved = read(bound(path, pin))
    require(saved['schema'] == SCHEMA and saved['implementation'] == implementation(), 'intake_version_changed')
    actual = prepare_task(**saved['inputs'])
    require(actual == saved, 'intake_content_or_evidence_changed')
    return actual


def open_task(path, pin, *, purpose, expected_combination_id):
    """Return a native model only after exact intent and purpose admission."""
    require(purpose in USES, 'unsupported_use:' + purpose)
    saved = read(bound(path, pin))
    require(saved.get('combination_id') == expected_combination_id, 'requested_combination_mismatch')
    current = revalidate_task(path, pin)
    decision = current['qualification'][purpose]
    require(decision['qualified'], 'unqualified_use:' + purpose + ':' + ','.join(decision['reasons']))
    inputs = current['inputs']
    if inputs['primitive_record'] is None:
        require(purpose == 'candidate_inspection', 'source_has_no_dynamic_qualification')
        ref = inputs['static_record']
        model, receipt = static.load_admitted(inputs['package'], ref['path'], ref['sha256'], purpose='static_inspection')
    else:
        ref = inputs['primitive_record']
        model, receipt = primitive.load_admitted(ref['root'], ref['path'], ref['sha256'],
            purpose=purpose, expected_scope_sha256=current['identity']['scope_sha256'])
    return model, dict(schema='generator-task-admission/v1', admission='passed', purpose=purpose,
        intake_sha256=pin, combination_id=expected_combination_id,
        model=current['current_model'], scope=current['inputs']['intent']['scope'],
        upstream_receipt=receipt, new_physics_steps=0,
        collection_authorized=purpose == 'qualified_collection', export_authorized=purpose == 'qualified_export')


def write_intake(output, value):
    destination = Path(output).resolve()
    protected = [value['inputs']['package'], value['inputs']['generator_output']]
    if value['inputs']['primitive_record']:
        protected.append(value['inputs']['primitive_record']['root'])
    require(not any(destination.is_relative_to(Path(p).resolve()) for p in protected),
            'intake_must_not_modify_frozen_inputs')
    write_new(destination, value)
