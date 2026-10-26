"""Independent saved-world-trajectory analysis for the bounded P021 experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def bound(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def check(record):
    actual = bound(record['path'])
    if actual['sha256'] != record['sha256'] or actual['bytes'] != record['bytes']:
        raise ValueError('Changed analysis input: ' + record['path'])


def rolling_force_support(force_times, duration, width):
    times = sorted(set(t for t in force_times if 0 <= t <= duration))
    intervals = np.diff([0.0,*times,duration])
    maximum_gap = float(intervals.max()) if len(intervals) else float(duration)
    return {'passed':bool(times) and duration >= width and maximum_gap <= width+1e-9,
            'maximum_force_observation_gap_s':maximum_gap,'unique_force_timestamps':len(times),
            'rolling_window_s':width,'scope':'every rolling window wholly within action start to stopping time'}


def engineering_result_check(result):
    """Independent fail-closed check; never trust a completed outer workflow."""
    required = {'final_scene_unchanged','exact_object_ids_bound','compiled_geometry_and_inertia_bound',
                'all_states_finite','actual_target_contacts_observed','actual_contact_parameters_match',
                'no_nonfloor_contact','trajectory_inside_room','no_simulator_warnings'}
    gates = result.get('engineering_gates', {})
    return (result.get('status') == 'completed' and result.get('simulation_completed') is True
            and required <= gates.keys() and all(value is True for value in gates.values())
            and result.get('simulator_warnings') == [] and result.get('failures') == [])


def refresh_classification(obj):
    analytical = {'near_plane_sliding','bounded_nonforward_energy','analytic_applicable',
                  'analytic_stopping_distance','analytic_stopping_time','forward_energy_dominates_while_moving'}
    obj['dynamic_health_passed'] = all(value is True for key, value in obj['gates'].items() if key not in analytical)
    obj['analytic_status'] = ('applicable' if obj['gates']['analytic_applicable'] else 'not_applicable')
    obj['benchmark_passed'] = obj['dynamic_health_passed'] and all(value is True for value in obj['gates'].values())
    # Explicit compatibility alias: this means the controlled sliding benchmark,
    # never proof of invalid friction or real-world dynamics.
    obj['passed'] = obj['benchmark_passed']


def analyze_saved_world(dense, binding, spec, thresholds):
    """Do not call simulator, generated metrics, or contact-configuration code."""
    identifiers = dense['object_ids'].tolist()
    if set(identifiers) != set(binding['objects']) or len(set(identifiers)) != len(identifiers):
        raise ValueError('Dense world object IDs differ from bound geometry')
    t = dense['action_time_s']
    action = np.flatnonzero(t >= 0)
    if len(action) < 3 or not np.all(np.diff(t[action]) > 0):
        raise ValueError('Action timestamps missing or not strictly increasing')
    dt = float(spec['simulation']['dt'])
    if not np.allclose(np.diff(t[action]), dt, atol=1e-9, rtol=0):
        raise ValueError('Dense saved action does not contain every physics timestep')
    if abs(t[action[0]]) > 1e-9 or abs(t[action[-1]]-spec['simulation']['action_s']) > 1e-9:
        raise ValueError('Saved action duration differs from specification')
    tail = action[t[action] >= t[action[-1]]-thresholds['residual_window_s']-1e-9]
    velocity0 = np.asarray(spec['simulation']['initial_velocity_m_s'], dtype=float)
    speed0 = float(np.linalg.norm(velocity0[:2]))
    direction = velocity0[:2]/speed0
    transverse = np.array([-direction[1],direction[0]])
    mu = .9 if spec['method'] == 'B0_bound_control' else spec['floor_mu']
    expected_d, expected_t = speed0**2/(2*mu*9.81), speed0/(mu*9.81)
    floor_z = binding['floor']['support_z_m']
    result = {}
    for index, identifier in enumerate(identifiers):
        matrix = dense['matrix_world_z_up'][:,index]
        linear = dense['linear_velocity_m_s'][:,index]
        angular = dense['angular_velocity_rad_s'][:,index]
        bounds = dense['world_bounds_z_up'][:,index]
        if not all(np.isfinite(a).all() for a in (matrix,linear,angular,bounds)):
            raise ValueError('Nonfinite world state: '+identifier)
        delta = matrix[action,:3,3]-matrix[action[0],:3,3]
        forward = delta[:,:2]@direction
        lateral = float(np.max(np.abs(delta[:,:2]@transverse)))
        speed = np.linalg.norm(linear[action,:2],axis=1)
        prior = action[0]-1
        if prior < 0:
            raise ValueError('Pre-impulse settled state missing')
        pre_impulse_settled = (abs(linear[prior,2]) <= thresholds['settled_vertical_speed_m_s']
            and np.linalg.norm(angular[prior]) <= thresholds['settled_angular_speed_rad_s']
            and dense['floor_contact_count'][prior,index] > 0)
        sliding = speed > thresholds['stopped_speed_m_s']
        support_complete = bool(np.all(dense['floor_contact_count'][action[sliding],index] > 0))
        max_sliding_angular = float(np.linalg.norm(angular[action[sliding]],axis=1).max()) if sliding.any() else 0.0
        obj = binding['objects'][identifier]
        mass = float(obj['compiled']['mass_kg'])
        inertia = np.asarray(obj['compiled']['diagonal_inertia_kg_m2'])
        w,x,y,z = np.asarray(obj['compiled']['inertial_quaternion_wxyz'])
        inertia_rotation = np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
            [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
            [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
        omega_body = np.einsum('ti,tij->tj',angular[action],matrix[action,:3,:3])
        omega_inertia = omega_body@inertia_rotation
        nonforward_ke = .5*mass*(linear[action,2]**2+(linear[action,:2]@transverse)**2)
        rotational_ke = .5*np.sum(omega_inertia**2*inertia,axis=1)
        potential_rise = mass*9.81*np.maximum(0,delta[:,2])
        extra_energy_fraction = float(((nonforward_ke+rotational_ke+potential_rise)/(.5*mass*speed0**2)).max())
        horizontal_ke = .5*mass*speed**2
        current_fraction = ((nonforward_ke+rotational_ke+potential_rise) /
                            np.maximum(horizontal_ke, .5*mass*thresholds['stopped_speed_m_s']**2))
        dominated = sliding & (current_fraction > 1.)
        # Energy dominance is a diagnostic of lost 1-D scope, not a new solver
        # correctness threshold. Near zero, the declared stop-speed floor avoids
        # division by zero and tiny-rest-state noise.
        forward_dominates = not bool(dominated.any())
        moving = np.flatnonzero(speed > thresholds['stopped_speed_m_s'])
        stop = int(moving[-1]+1) if len(moving) else 0
        stopped = stop < len(action) and t[action[-1]]-t[action[stop]] >= thresholds['minimum_stopped_duration_s']
        distance = float(forward[stop]) if stopped else None
        stopping_time = float(t[action[stop]]) if stopped else None
        initial_up_body = matrix[0,:3,:3].T @ np.array([0.,0.,1.])
        up_world = matrix[action,:3,:3] @ initial_up_body
        tilt = float(np.degrees(np.arccos(np.clip(up_world[:,2],-1,1))).max())
        gap = bounds[:,0,2]-floor_z
        penetration = float(max(0,-gap.min()))
        suspension = float(max(0,gap[tail].max()))
        near_plane_gap = float(max(0,gap[action[sliding]].max())) if sliding.any() else 0.0
        linear_rms = float(np.sqrt(np.mean(np.sum(linear[tail]**2,axis=1))))
        angular_rms = float(np.sqrt(np.mean(np.sum(angular[tail]**2,axis=1))))
        outside = ((bounds[:,0,0] < -1e-6)|(bounds[:,0,1] < -1e-6)|
            (bounds[:,1,0] > spec['room']['width']+1e-6)|
            (bounds[:,1,1] > spec['room']['length']+1e-6)|
            (bounds[:,1,2] > spec['room']['height']+1e-6))
        applicable = bool(pre_impulse_settled and
            near_plane_gap <= thresholds['analytic_max_plane_gap_m'] and
            extra_energy_fraction <= thresholds['analytic_max_nonforward_energy_fraction'] and
            forward_dominates and
            tilt <= thresholds['analytic_max_tilt_degrees'] and
            lateral <= thresholds['analytic_max_lateral_m'] and not outside.any())
        distance_pass = stopped and abs(distance-expected_d) <= max(thresholds['distance_absolute_m'], thresholds['distance_relative']*expected_d)
        time_pass = stopped and abs(stopping_time-expected_t) <= max(thresholds['time_absolute_s'], thresholds['time_relative']*expected_t)
        gates = {'initial_horizontal_velocity_matches': bool(np.allclose(linear[action[0],:2],velocity0[:2],atol=1e-8,rtol=0)),
            'finite_states': True, 'inside_room': not bool(outside.any()),
            'floor_penetration': penetration <= thresholds['floor_penetration_m'],
            'final_floor_suspension': suspension <= thresholds['floor_suspension_m'],
            'residual_linear_velocity': linear_rms <= thresholds['residual_linear_rms_m_s'],
            'residual_angular_velocity': angular_rms <= thresholds['residual_angular_rms_rad_s'],
            'pre_impulse_settled':bool(pre_impulse_settled),
            'near_plane_sliding':near_plane_gap <= thresholds['analytic_max_plane_gap_m'],
            'bounded_nonforward_energy':extra_energy_fraction <= thresholds['analytic_max_nonforward_energy_fraction'],
            'forward_energy_dominates_while_moving': forward_dominates,
            'analytic_applicable': applicable,
            'analytic_stopping_distance': bool(distance_pass) if applicable else None,
            'analytic_stopping_time': bool(time_pass) if applicable else None}
        result[identifier] = {'stopping_distance_m': distance, 'final_forward_displacement_m':float(forward[-1]),
            'stopping_time_s': stopping_time, 'expected_stopping_distance_m': expected_d,
            'expected_stopping_time_s': expected_t, 'actual_effective_mu_expected':mu,
            'max_action_tilt_degrees': tilt, 'max_lateral_displacement_m': lateral,
            'max_sliding_angular_speed_rad_s':max_sliding_angular,
            'strict_endpoint_contact_continuity_passed':support_complete,
            'strict_continuity_is_not_required_for_macroscopic_acceptance':True,
            'max_sliding_plane_gap_m':near_plane_gap,
            'max_nonforward_energy_fraction':extra_energy_fraction,
            'max_nonforward_to_current_horizontal_energy_ratio_while_moving':float(current_fraction[sliding].max()) if sliding.any() else 0.,
            'nonforward_dominated_moving_sample_count':int(dominated.sum()),
            'analytic_inapplicability_reasons': [key for key, value in {
                'unsettled_impulse': not pre_impulse_settled,
                'plane_gap_exceeds_declared_scope': near_plane_gap > thresholds['analytic_max_plane_gap_m'],
                'nonforward_energy_exceeds_declared_scope': extra_energy_fraction > thresholds['analytic_max_nonforward_energy_fraction'],
                'nonforward_energy_dominates_current_horizontal_motion': not forward_dominates,
                'tilt_exceeds_declared_scope': tilt > thresholds['analytic_max_tilt_degrees'],
                'lateral_motion_exceeds_declared_scope': lateral > thresholds['analytic_max_lateral_m'],
                'outside_room': bool(outside.any())}.items() if value],
            'pre_impulse_vertical_velocity_m_s':float(linear[prior,2]),
            'pre_impulse_angular_speed_rad_s':float(np.linalg.norm(angular[prior])),
            'max_floor_penetration_m': penetration, 'last_window_max_floor_suspension_m': suspension,
            'last_window_linear_rms_m_s':linear_rms, 'last_window_angular_rms_rad_s':angular_rms,
            'action_samples': len(action), 'gates':gates, 'passed':all(gates.values())}
        refresh_classification(result[identifier])
    return result


def analyze_workflow(directory, protocol):
    directory = Path(directory)
    workflow = json.loads((directory/'workflow_result.json').read_text())
    expected_stages=['request_source_layout_assembly_geometry','actual_mesh_dynamics','actual_dynamic_and_final_rendering']
    if (workflow.get('status')!='completed_pending_independent_analysis_and_AI_visual_review'
            or [x.get('stage') for x in workflow.get('stages',[])]!=expected_stages
            or any(x.get('status')!='complete' for x in workflow['stages'])):
        raise ValueError('Full workflow stages have not completed')
    for record in workflow['artifacts']:
        check(record)
    for relative,key in [('scene/geometry_qa.json','accepted'),('scene/asset_source_policy.json','ok'),('scene/layout_qa.json','ok')]:
        if json.loads((directory/relative).read_text()).get(key) is not True:
            raise ValueError('Full scene prerequisite failed: '+relative)
    spec = json.loads((directory/'physics_input.json').read_text())
    physics_result = json.loads((directory/'physics'/'physics_result.json').read_text())
    engineering_ok = engineering_result_check(physics_result)
    for record in physics_result.get('artifacts', {}).values():
        check(record)
    binding = json.loads((directory/'physics'/'physics_binding.json').read_text())
    trajectory = json.loads((directory/'physics'/'trajectory.json').read_text())
    for record in (binding['scene_glb'],binding['model_xml'],binding['spec'],trajectory['binding'],trajectory['dense_state']):
        check(record)
    thresholds = protocol['thresholds']
    with np.load(directory/'physics'/'dense_state.npz',allow_pickle=False) as dense:
        objects = analyze_saved_world(dense,binding,spec,thresholds)
    expected_mu = .9 if spec['method']=='B0_bound_control' else spec['floor_mu']
    expected_friction = np.array([expected_mu,expected_mu,.05,.001,.001])
    coverage = {k:0 for k in objects}
    force_times = {k:[] for k in objects}
    parameter_failures, nonfloor, records = 0, 0, 0
    with (directory/'physics'/'contacts.jsonl').open() as stream:
        for line in stream:
            contact = json.loads(line)
            records += 1
            # Read actual solver contacts, not the backend's aggregate pass flag.
            identifier = contact.get('object_id')
            if identifier not in coverage:
                nonfloor += 1
                continue
            coverage[identifier] += 1
            if contact.get('action_time_s') is not None and contact['efc_address'] >= 0 and contact['force_contact_frame'][0] > 1e-8*binding['objects'][identifier]['compiled']['mass_kg']*9.81:
                force_times[identifier].append(float(contact['action_time_s']))
            correct = (contact['condim']==3 and
                np.allclose(contact['friction'],expected_friction,atol=thresholds['contact_parameter_atol'],rtol=0) and
                np.allclose(contact['solref'],[.01,1],atol=thresholds['contact_parameter_atol'],rtol=0) and
                np.allclose(contact['solimp'],[.9,.95,.001,.5,2.],atol=thresholds['contact_parameter_atol'],rtol=0) and
                np.allclose(contact['solreffriction'],[0,0],atol=thresholds['contact_parameter_atol'],rtol=0))
            parameter_failures += int(not correct)
    render = json.loads((directory/'renders'/'render_manifest.json').read_text())
    actions = [f for f in trajectory['frames'] if f['phase']=='action']
    diagnostics = trajectory.get('diagnostic_frames', [])
    expected_frames = [trajectory['frames'][0], *actions, *diagnostics, trajectory['frames'][-1], trajectory['frames'][-1]]
    render_complete = (render.get('ok') is True and render.get('rendered_png_count')==len(expected_frames)
        and render.get('action_frame_count')==len(actions)
        and render.get('diagnostic_frame_count', 0)==len(diagnostics)
        and len(render.get('frames', []))==len(expected_frames))
    for actual, expected in zip(render['frames'], expected_frames):
        render_complete = render_complete and actual.get('phase')==expected['phase'] and actual.get('action_time_s')==expected['action_time_s']
    for frame in render['frames']:
        check(frame['image'])
    for identifier,obj in objects.items():
        stop_t = obj['stopping_time_s']
        width = thresholds['force_support_window_s']
        support = rolling_force_support(force_times[identifier],stop_t if stop_t is not None else spec['simulation']['action_s'],width)
        supported = support['passed']
        obj['positive_normal_force_rolling_support'] = support
        obj['gates']['force_bearing_support_in_each_observation_window'] = bool(supported)
        if not supported or nonfloor:
            obj['gates']['analytic_applicable'] = False
            for gate in ('analytic_stopping_distance','analytic_stopping_time'):
                obj['gates'][gate] = None
            obj['analytic_inapplicability_reasons'].append('insufficient_support_or_nonfloor_contact')
        refresh_classification(obj)
    numerical = physics_result.get('numerical_diagnostics', {})
    numerical_ok = (numerical.get('schema')=='p021-numerical-sensitivity/v1'
        and len(numerical.get('comparisons', []))==3 and numerical.get('base_step_resolved') is True
        and all(c.get('passed') is True for c in numerical['comparisons'][:2]))
    gates = {'all_current_evidence_hashes_match':True,'contact_parameter_values':parameter_failures==0,
        'physics_engineering_success':engineering_ok, 'base_timestep_resolved':numerical_ok,
        'each_object_actual_floor_contact':all(coverage.values()),'no_nonfloor_contacts':nonfloor==0,
        'complete_actual_dynamic_render':render_complete,'all_object_dynamic_health':all(x['dynamic_health_passed'] for x in objects.values())}
    return {'schema':'p021-independent-physics-analysis/v2','run_id':spec['run_id'],
        'method':spec['method'],'floor_mu':spec['floor_mu'],'development':spec['development'],
        'objects':objects,'contact_record_count':records,'contact_coverage':coverage,
        'contact_parameter_failure_count':parameter_failures,'nonfloor_contact_count':nonfloor,
        'gates':gates,'automated_passed':all(gates.values()),'visual_review_complete':False,
        'benchmark_passed':all(gates.values()) and all(x['benchmark_passed'] for x in objects.values()),
        'numerical_diagnostics':numerical, 'physics_engineering_failures':physics_result.get('failures'),
        'human_review':None,'external_physics_validated':False,
        'workflow':bound(directory/'workflow_result.json'),'analysis_code':bound(Path(__file__)),
        'thresholds':thresholds,'camera_and_settings_sha256':render['camera_and_settings_sha256']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=analyze_workflow(args.workflow,json.loads(args.protocol.read_text()))
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({'run_id':result['run_id'],'automated_passed':result['automated_passed']}))


if __name__=='__main__':
    main()
