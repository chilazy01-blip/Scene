"""Import bound raw measurements into a scope-specific quality record."""
from pathlib import Path
import numpy as np

from sage.experiments.embodied_scene_quality_v1.quality import read_pinned_record
from .contracts import (SCHEMA, Rejected, bound, read, read_ref, reference, fingerprint, require,
                        metric, implementation, load_protocol, decisions, digest)
from .geometry import fidelity, fidelity_passed
from .primitives import read_raw, evaluate_trace


def load_binding(root, protocol_pin, bundle_pin):
    root = Path(root)
    protocol = load_protocol(root/'protocol/PROTOCOL.json', protocol_pin)
    bundle = read(bound(root/'BUNDLE.json', bundle_pin))
    binding = read_ref(bundle['binding'])
    require(binding['protocol_sha256'] == protocol_pin, 'model_protocol_scope_mismatch')
    require(binding['implementation'] == implementation(), 'implementation_changed')
    require(binding['scope_sha256'] == fingerprint(protocol['scope']), 'scope_binding_mismatch')
    # Preserve v1's record and check the source bytes without running its old experiments.
    v1 = read_pinned_record(protocol['phase1_record'], protocol['phase1_record_sha256'])
    source = Path(protocol['source_package'])
    bound(source/'FILES.json', v1['assessment']['subject']['package_manifest_sha256'])
    for name, expected in v1['assessment']['subject']['files'].items():
        bound(source/name, expected)
    for item in v1['assessment']['sources'].values():
        if item['sha256'] is not None:
            bound(item['path'], item['sha256'])
    require(binding['source_task_sha256'] == v1['assessment']['subject']['task_sha256'], 'task_binding_mismatch')
    for variant in binding['variants'].values():
        for key in ('xml', 'binary'):
            bound(variant[key]['path'], variant[key]['sha256'])
    require(binding['variants']['baseline']['invariants'] == binding['variants']['candidate']['invariants'],
            'nonbottom_invariant_mismatch')
    initial = read_ref(binding['initial_states'])
    require(initial['scope_sha256'] == binding['scope_sha256'], 'initial_scope_mismatch')
    require([x['key'] for x in initial['cases']] == [x['key'] for x in protocol['scope']['cases']], 'initial_case_population_mismatch')
    return protocol, bundle, binding, initial


def assess(root, protocol_pin, bundle_pin):
    protocol, bundle, binding, initials = load_binding(root, protocol_pin, bundle_pin)
    cases = {c['key']: c for c in protocol['scope']['cases']}
    initial_map = {c['key']: c for c in initials['cases']}
    task = read(Path(protocol['source_package'])/'task.json')
    geometry = read_raw(binding['geometry_raw'])
    measurements = {variant: fidelity(geometry['source_height'], geometry[variant+'_height'])
                    for variant in ('baseline', 'candidate')}
    gpass = fidelity_passed(measurements['candidate'], protocol['geometry']['qualification'])
    metrics = {
        'input_binding': metric('pass', dict(protocol_sha256=protocol_pin, bundle_sha256=bundle_pin,
            model_sha256=binding['variants']['candidate']['binary']['sha256'],
            task_sha256=binding['source_task_sha256'], scope_sha256=binding['scope_sha256']), 'sha256',
            {'source': 'registered protocol and prepared model freeze', 'rule': 'all input hashes and versions match'},
            [bundle['binding'], binding['initial_states']], 'Exact isolated model, original source task and finite case scope are bound'),
        'geometry_fidelity': metric('pass' if gpass else 'fail', measurements,
            {'height': 'm', 'coverage': 'fraction'},
            {'source': protocol['geometry']['threshold_source'], **protocol['geometry']['qualification']},
            [binding['geometry_raw']], 'Independent shifted-ray samples; local top/bottom column approximation, not material calibration'),
    }
    expected = {f'{variant}/{key}': (variant, 'primary', protocol['physics']['base_dt_s'])
                for variant in ('baseline', 'candidate') for key in cases}
    expected.update({f'refined/{key}': ('candidate', 'refinement', protocol['physics']['refined_dt_s'])
                     for key in protocol['numerical']['refinement_cases']})
    expected.update({f'replay/{key}': ('candidate', 'replay', protocol['physics']['base_dt_s'])
                     for key in protocol['numerical']['replay_cases']})
    require(set(bundle['trials']) <= expected.keys(), 'unregistered_attempt_evidence')
    missing = sorted(expected.keys()-bundle['trials'].keys())
    evaluated, raw_by_label, attempts = {}, {}, {}
    for label, ref in bundle['trials'].items():
        attempt = read_ref(ref); variant, purpose, dt = expected[label]; key = label.split('/')[1]
        require(attempt['case'] == key and attempt['variant'] == variant and attempt['purpose'] == purpose
                and attempt['dt_s'] == dt, 'attempt_registration_mismatch:' + label)
        require(attempt['binding_sha256'] == bundle['binding']['sha256'], 'attempt_model_binding_mismatch:' + label)
        require(attempt['robot_present'] is False, 'robot_scope_mismatch')
        require(attempt['expected_response'] == cases[key]['expected_response'], 'attempt_expectation_mismatch')
        require(attempt['initial_state_sha256'] == fingerprint(initial_map[key]['integration_state'][variant]),
                'attempt_initial_state_mismatch:' + label)
        initial = read_ref(attempt['initial']); raw = read_raw(attempt['raw'])
        require(np.array_equal(initial['complete_state'], initial_map[key]['integration_state'][variant]),
                'saved_initial_state_mismatch:' + label)
        require(np.allclose(initial['qpos'], initial_map[key]['qpos'], rtol=0, atol=1e-12)
                and np.allclose(initial['qvel'], initial_map[key]['qvel'], rtol=0, atol=1e-12), 'initial_qpos_qvel_mismatch')
        evaluated[label] = evaluate_trace(raw, initial, attempt, binding['variants'][variant]['description'], task, protocol)
        raw_by_label[label] = raw; attempts[label] = attempt
    stable_keys = [key for key, c in cases.items() if c['expected_response'] == 'stable']
    candidate_labels = ['candidate/'+key for key in stable_keys]
    available = [evaluated[label] for label in candidate_labels if label in evaluated]
    dynamic = 'unknown' if len(available) != len(stable_keys) else 'pass' if all(x['placement_stable'] for x in available) else 'fail'
    feasible = 'unknown' if len(available) != len(stable_keys) else 'pass' if all(
        x['initial_admitted'] and x['engineering_passed'] for x in available) else 'fail'
    metrics['dynamic_release'] = metric(dynamic, dict(expected_stable_cases=len(stable_keys),
        completed=len(available), stable=sum(x['placement_stable'] for x in available),
        rows={key: evaluated.get('candidate/'+key) for key in cases}),
        {'position': 'm', 'time': 's', 'force': 'N', 'tilt': 'deg'},
        {'source': protocol['physics']['threshold_source'], **protocol['physics']['stable_thresholds'],
         'max_target_penetration_m': protocol['physics']['max_target_penetration_m']},
        [bundle['trials'][k] for k in candidate_labels if k in bundle['trials']],
        'All ten declared stable cases must pass; challenge outcomes are retained outside that qualification')
    metrics['primitive_task_feasibility'] = metric(feasible, dict(registered=len(stable_keys),
        initial_admitted=sum(x['initial_admitted'] for x in available),
        engineering_passed=sum(x['engineering_passed'] for x in available)), 'case',
        {'source': 'isolated primitive protocol', 'rule': 'valid initial states and completed safe primitive execution'},
        [bundle['trials'][k] for k in candidate_labels if k in bundle['trials']],
        'Only the named isolated release primitive; no robot reachability, grasp, entry or retreat claim')
    refinement = []
    threshold = protocol['numerical']['refinement']
    for key in protocol['numerical']['refinement_cases']:
        a, b = evaluated.get('candidate/'+key), evaluated.get('refined/'+key)
        if a is None or b is None:
            continue
        pos = float(np.linalg.norm(np.asarray(a['terminal_position_m'])-b['terminal_position_m']))
        tilt = abs(a['terminal_tilt_deg']-b['terminal_tilt_deg']) if a['terminal_tilt_deg'] is not None and b['terminal_tilt_deg'] is not None else None
        speed = abs(a['terminal_speed_m_s']-b['terminal_speed_m_s']) if a['terminal_speed_m_s'] is not None and b['terminal_speed_m_s'] is not None else None
        event = abs(a['first_bottom_contact_time_s']-b['first_bottom_contact_time_s']) if a['first_bottom_contact_time_s'] is not None and b['first_bottom_contact_time_s'] is not None else None
        passed = (a['engineering_passed'] and b['engineering_passed'] and a['placement_stable'] == b['placement_stable']
                  and pos <= threshold['terminal_position_m_max'] and tilt is not None
                  and tilt <= threshold['terminal_tilt_deg_max'] and speed is not None
                  and speed <= threshold['terminal_speed_m_s_max'] and event is not None
                  and event <= threshold['first_bottom_contact_time_s_max'])
        refinement.append(dict(case=key, passed=bool(passed), terminal_position_difference_m=pos,
            terminal_tilt_difference_deg=tilt, terminal_speed_difference_m_s=speed,
            first_bottom_contact_difference_s=event, classification_agrees=a['placement_stable']==b['placement_stable']))
    replay = []
    for key in protocol['numerical']['replay_cases']:
        a, b = raw_by_label.get('candidate/'+key), raw_by_label.get('replay/'+key)
        if a is None or b is None:
            continue
        errors = {}; passed = True
        for field in ('time', 'qpos', 'qvel', 'full_state', 'contacts', 'warnings'):
            equal_shape = a[field].shape == b[field].shape
            error = float(np.max(abs(a[field]-b[field]))) if equal_shape and a[field].size else (0. if equal_shape else None)
            passed &= equal_shape and error <= protocol['numerical']['replay_state_atol']
            errors[field] = dict(equal_shape=equal_shape, maximum_absolute_error=error)
        replay.append(dict(case=key, passed=bool(passed), fields=errors))
    ncomplete = len(refinement) == len(protocol['numerical']['refinement_cases']) and len(replay) == len(protocol['numerical']['replay_cases'])
    nstate = 'unknown' if not ncomplete else 'pass' if all(x['passed'] for x in refinement+replay) else 'fail'
    metrics['numerical_reliability'] = metric(nstate, dict(refinement=refinement, replay=replay),
        {'position': 'm', 'time': 's', 'tilt': 'deg'},
        {'source': protocol['numerical']['threshold_source'], **threshold,
         'replay_state_atol': protocol['numerical']['replay_state_atol']},
        [ref for key, ref in bundle['trials'].items() if key.startswith(('refined/', 'replay/'))],
        'Three preregistered macro dt comparisons and two fresh-process full-state replays; not global convergence')
    for name, reason in [('full_robot_task', 'Robot removed; grasp/entry/retreat and complete robot contact unverified'),
                         ('observation_export', 'No visual/action-time export evidence for this derived model'),
                         ('cross_asset_coverage', 'One development asset/support combination; no independent validation')]:
        metrics[name] = metric('unknown', None, None, {'source': 'scope exclusions'}, [], reason)
    total = sum(x['new_physics_steps'] for x in evaluated.values())
    require(total <= protocol['budget']['max_physics_steps'] and len(evaluated) <= protocol['budget']['max_new_physical_attempts'], 'physics_budget_exceeded')
    return dict(schema=SCHEMA, implementation=implementation(), protocol_sha256=protocol_pin,
        bundle_sha256=bundle_pin, scope=protocol['scope'], scope_sha256=binding['scope_sha256'],
        subject=dict(source_task_sha256=binding['source_task_sha256'],
                     candidate_model_sha256=binding['variants']['candidate']['binary']['sha256'],
                     candidate_physical_parameters=binding['variants']['candidate']['description']),
        metrics=metrics, qualification=decisions(metrics), missing_attempts=missing,
        all_attempts=evaluated, geometry=measurements,
        cost=dict(attempts=len(evaluated), new_physics_steps=total,
                  attempt_wall_seconds=sum(x['wall_seconds'] for x in attempts.values()),
                  candidate_model_geoms=binding['variants']['candidate']['description']['model_ngeom'],
                  new_policy_forwards=0, new_training=0, new_collection=0, qualified_training_episodes_added=0))


def load_admitted(root, record_path, record_pin, *, purpose, expected_scope_sha256):
    record = read(bound(record_path, record_pin))
    require(record['schema'] == SCHEMA and record['implementation'] == implementation(), 'record_version_changed')
    require(record['scope_sha256'] == expected_scope_sha256, 'requested_scope_mismatch')
    require(purpose in record['qualification'], 'unsupported_use')
    # All status and requirement lists are recomputed from raw evidence.
    actual = assess(root, record['protocol_sha256'], record['bundle_sha256'])
    require(actual == record, 'record_assessment_changed')
    decision = actual['qualification'][purpose]
    require(decision['qualified'], 'unqualified_use:' + purpose + ':' + ','.join(decision['reasons']))
    _, bundle, binding, _ = load_binding(root, record['protocol_sha256'], record['bundle_sha256'])
    import mujoco
    desc = binding['variants']['candidate']
    require(mujoco.__version__ == desc['description']['mujoco_version'], 'engine_version_changed')
    model = mujoco.MjModel.from_binary_path(str(bound(desc['binary']['path'], desc['binary']['sha256'])))
    return model, dict(schema='scene-quality-primitive-admission/v2', purpose=purpose,
        record_sha256=record_pin, scope_sha256=expected_scope_sha256, scope=record['scope'],
        model_sha256=desc['binary']['sha256'], task_sha256=binding['source_task_sha256'],
        required=decision['required'], physics_steps_started=0, admission='passed')
