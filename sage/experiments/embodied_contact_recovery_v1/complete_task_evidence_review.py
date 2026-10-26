"""Evidence-bound review of full development tasks and remaining production gates."""
import csv
import sys
from pathlib import Path
from .work import E, c, finish


def main(config):
    cfg = c.read(config)
    state, plan = c.read(cfg['state_snapshot']), c.read(cfg['plan_snapshot'])
    tasks = []
    for item in cfg['tasks']:
        folder = E/'jobs'/item['job']
        result = c.read(folder/'RESULT.json')
        audit_path = E/'jobs'/(item['job']+'_audit')/'AUDIT.json'
        audit = c.read(audit_path)
        quality = c.read(item['quality'])
        trace = result['trace_summary']
        assert audit['passed'] and all(x == 0 for x in audit['max_errors'].values())
        assert audit['independent_process_continuous_reintegration_and_policy_recompute']
        assert not result['production_accepted'] and not result['research_task_passed']
        assert quality['source_sha256'] == c.sha(folder/'episode/TRACE.h5')
        assert trace['physics_steps'] > 0
        metrics = quality['metrics']
        tasks.append({'key':item['key'], 'job':item['job'], 'physics_steps':trace['physics_steps'],
            'duration_s':trace['physics_steps']*.0025, 'maximum_penetration_m':trace['max_penetration_m'],
            'object_max_lift_m':metrics.get('object_max_lift_m'), 'grasped_carry_m':metrics.get('grasped_carry_m'),
            'terminal_object_tilt_max_deg':metrics.get('terminal',{}).get('object_tilt_max_deg'),
            'failed_recorded_quality_gates':[k for k,v in quality['gates'].items() if v is False],
            'forbidden_contact_pairs':quality['forbidden_pairs'],
            'source_abort':result['source_result']['abort'], 'failure_interpretation':item['failure_interpretation'],
            'source_task_success':False, 'production_accepted':False, 'independent_full_audit_passed':True,
            'independent_full_audit_all_saved_datasets_exact':True,
            'plant_guard_every_substep':trace.get('plant_parameters_unchanged_each_substep'),
            'plant_guard_note':'Null means the earlier trace predates this per-step guard; independent replay still passed.' if 'plant_parameters_unchanged_each_substep' not in trace else None,
            'source_result_sha256':c.sha(folder/'RESULT.json'), 'trace_sha256':c.sha(folder/'episode/TRACE.h5'),
            'audit_sha256':c.sha(audit_path), 'quality_sha256':c.sha(item['quality'])})
    assert len(tasks) == state['spent']['task_attempts']-plan['initial_spent']['task_attempts'] == 8
    assert state['methods']['C_measured_contact_recovery']['scientific_failures'] == 3
    assert state['methods']['D_object_pose_planning']['scientific_failures'] == 5
    assert all(v['closed'] for v in state['methods'].values())
    foot = c.read(E/'D_GUARD_LANDING_FOOT_NUMERICAL_REVIEW.json')
    hand = c.read(E/'D_GUARD_LANDING_HAND_NUMERICAL_REVIEW.json')
    assert not foot['local_numerical_gates_passed'] and hand['local_hand_numerical_passed']
    scale = c.read(E/'CONTACT_MODEL_SCALE_REVIEW.json')
    scales = [q for source in scale['sources'] for contact in source['contacts'] for q in contact['reference_scales']]
    assert scales and all(not q['reference_safety_clamp_active'] for q in scales)
    generated = []
    for key in cfg['generated_static_jobs']:
        result = c.read(E/'jobs'/key/'RESULT.json')
        assert result['static_planner_passed'] and not result['dynamic_admission']
        generated.append({'job':key,'layout':result['layout'],'static_planner_passed':True,
                          'dynamic_admission':False,'result_sha256':c.sha(E/'jobs'/key/'RESULT.json')})
    report = {'complete':True,'new_physics_steps':0,'new_render_passes':0,'new_full_task_count':len(tasks),
        'tasks':tasks,'accepted_full_body_task_count':0,'qualified_full_task_yield':0.,
        'all_complete_tasks_independently_reintegrated_exactly':True,
        'new_development_slots_used':8,'new_comparison_tasks_used':0,'new_final_test_tasks_used':0,
        'unused_task_slots_are_gated_not_available_development_trials':10,
        'method_states':{k:{'closed':v['closed'],'scientific_failures':v['scientific_failures']} for k,v in state['methods'].items()},
        'latest_local_hand_numerical_gate_passed':True,'latest_local_foot_numerical_gate_passed':False,
        'whole_task_numerical_qualification_passed':False,
        'reference_safety_interpretation':{'source_review_sha256':c.sha(E/'CONTACT_MODEL_SCALE_REVIEW.json'),
            'primary_source':'https://mujoco.readthedocs.io/en/3.7.0/modeling.html#solver-parameters',
            'fixed_runtime_version':'3.7.0','document_rule_paraphrase':'For positive-format solref with reference safety enabled, the time constant is lower-bounded by twice the integration timestep.',
            'inference':'For the sampled actual contacts in all three reviewed trajectories, 20ms exceeds twice each tested timestep. The safety clamp does not explain their tested timestep sensitivity.',
            'scope_limit':'This excludes the sampled reference-clamp mechanism only; it does not establish physical calibration, numerical convergence, or correctness of every contact in a full task.'},
        'generated_development_static_evidence':generated,'generated_successful_dynamic_tasks':0,
        'effective_generated_scene_diversity_for_accepted_data':0,'training_updates':0,'learning_effect_verified':False,
        'explicit_budget_or_scope_amendment_receipts':{name:c.sha(E/name) for name in cfg['approval_receipts']},
        'production_blockers':['No full development task passed unchanged quality gates',
            'Shared foot timestep sensitivity remains outside position/speed gates',
            'Material, friction and force/transient limits lack empirical calibration',
            'Generated scenes are statically checked but have no accepted dynamic tasks',
            'No frozen comparison or fresh final-test admission; no downstream learning validation'],
        'next_scope_recommendation':'Use the archived contact and full-task regression fixtures to resolve foot-contact numerical/physical validity before allocating another full-task recovery campaign. Retain generator integration and standard data export as reusable infrastructure. Any new physical campaign requires a separately bounded scope; this report does not authorize one.',
        'clock':plan['clock'],'whole_run_closure_claim':False,'full_project_objective_achieved':False,
        'state_snapshot_sha256':c.sha(cfg['state_snapshot']),'plan_snapshot_sha256':c.sha(cfg['plan_snapshot'])}
    out = E/cfg['output']
    c.write(out, report)
    columns = ['key','physics_steps','duration_s','maximum_penetration_m','object_max_lift_m','grasped_carry_m','terminal_object_tilt_max_deg','source_abort','independent_full_audit_passed','production_accepted']
    with out.with_suffix('.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows({k:t[k] for k in columns} for t in tasks)
    finish(report)


if __name__ == '__main__':
    main(sys.argv[1])
