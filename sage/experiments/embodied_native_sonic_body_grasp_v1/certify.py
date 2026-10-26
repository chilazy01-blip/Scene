"""Certify the delivered full-task episode and reconcile every actual cost record."""
import argparse,os,resource
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from .protocol import read_bound_json,safe_save,_file_binding


def check(binding):
    assert _file_binding(Path(binding['path']))==binding,binding['path']


def run(root,report_path):
    trial=root/'trial_07';positive=read_bound_json(trial/'full/REPORT.json')
    audit=read_bound_json(trial/'full/AUDIT.json');replay=read_bound_json(trial/'continuous_replay/REPORT.json')
    delivery=read_bound_json(trial/'delivery/REVIEW.json');measure=read_bound_json(trial/'TASK_MEASUREMENTS.json')
    video=read_bound_json(trial/'actual_video/MANIFEST.json');force=read_bound_json(trial/'FORCE_CHECK.json')
    auth=read_bound_json(root/'SIX_HOUR_AUTHORIZATION.json')
    assert positive['task_passed'] and all(positive['gates'].values())
    assert audit['task_passed'] and all(audit['gates'].values())
    assert audit['max_pd_error_nm']==audit['max_contact_error']==audit['max_geometry_error_m']==0
    assert replay['passed'] and replay['physics_steps']==positive['physics_steps']==7576
    assert replay['initializations']==1 and replay['intermediate_state_injections']==0
    assert max(replay['maximum_absolute_error'].values())==0
    assert delivery['mechanically_qualified'] and delivery['positive_episode_count']==1
    assert delivery['all_decoded_frames']==video['frames']==1894
    assert measure['strict_held_base_net_displacement_m']>.5
    assert measure['all_carry_and_braking_samples_hand_contact_and_off_table']
    assert measure['final_cup_upright_cosine']>.98
    assert measure['maximum_last200_base_speed_m_s']<.06 and measure['maximum_last200_cup_speed_m_s']<.02
    assert force['maximum_hand_and_desk_force_error_n']<1e-8 and force['maximum_static_capacity_error']<1e-8
    for b in [positive['case'],positive['protocol'],positive['model'],positive['engine'],positive['trace'],positive['policy_io'],audit['implementation'],replay['implementation']]:check(b)
    for b in video['files'].values():check(b)
    with np.load(trial/'delivery/episode.npz',allow_pickle=False) as arrays:
        assert arrays['ctrl'].shape==(7576,43)
        assert arrays['qpos_after'].shape==(7576,57)
        assert arrays['qvel_after'].shape==(7576,55)
        assert len(arrays['stage'])==7576
        assert all(np.isfinite(arrays[key]).all() for key in arrays.files if arrays[key].dtype.kind in 'fiu')
    branches=[]
    for number in [1,2,4,5,6,7]:
        folder=root/f'trial_{number:02d}';r=read_bound_json(folder/'full/REPORT.json')
        a=read_bound_json(folder/'full/AUDIT.json');v=folder/('delivery' if number==7 else 'partial_delivery')/'REVIEW.json'
        d=read_bound_json(v)
        assert a['executed_control_reconstruction_passed']
        assert d['all_decoded_frames']==r['physics_steps']//4
        assert bool(d['mechanically_qualified'])==(number==7)
        assert (folder/'FORCE_CHECK.json').exists() and (folder/'grasp_detail/MANIFEST.json').exists()
        images=[folder/'grasp_detail/review.jpg',v.parent/'decoded_review.jpg']
        branches.append(dict(number=number,task_passed=r['task_passed'],stop_reason=r['stop_reason'],
            report=_file_binding(folder/'full/REPORT.json'),audit=_file_binding(folder/'full/AUDIT.json'),
            cost=_file_binding(folder/'cost/REPORT.json'),force=_file_binding(folder/'FORCE_CHECK.json'),
            delivery=_file_binding(v),primary_agent_reviewed_contact_sheets=[_file_binding(p) for p in images],
            every_video_frame_automatically_decoded=True,every_frame_manually_viewed=False,
            failure_diagnosis=None if number==7 else _file_binding(folder/'DIAGNOSIS.json')))
    ledger=read_bound_json(root/'COST.json');total=ledger['prior_native_steps'];costs=[]
    for item in ledger['reservations']:
        p=Path(item['output'])/'REPORT.json';r=read_bound_json(p);steps=r['physics_steps']
        assert 0<=steps<=item['maximum_steps'];total+=steps;costs.append(dict(report=_file_binding(p),physics_steps=steps))
    assert total==84564 and total-ledger['prior_native_steps']==18360
    assert read_bound_json(root/'trial_03/cost/REPORT.json')['physics_steps']==0
    assert datetime.now(timezone.utc).timestamp()<auth['deadline_epoch_utc']
    artifacts={str(p.relative_to(trial)):_file_binding(p) for p in [trial/'full/REPORT.json',trial/'full/AUDIT.json',trial/'continuous_replay/REPORT.json',trial/'delivery/REVIEW.json',trial/'delivery/episode.npz',trial/'actual_video/MANIFEST.json',trial/'actual_video/motion.mp4',trial/'TASK_MEASUREMENTS.json',trial/'FORCE_CHECK.json']}
    result=dict(schema='native-six-hour-full-task-certified/v1',certified=True,
        created_utc=datetime.now(timezone.utc).isoformat(),authorization=_file_binding(root/'SIX_HOUR_AUTHORIZATION.json'),
        implementation=_file_binding(Path(__file__)),report=_file_binding(report_path),artifacts=artifacts,
        original_task_gates_all_passed=True,independent_audit_all_passed=True,original_init_full43control_replay_bitwise=True,
        video_all1894frames_decoded=True,additional_upright_cup_review_passed=True,
        manual_video_review_pending=False,manual_review_method='Primary agent viewed decoded stage contact sheets and grasp closeups; not manual viewing of every frame.',
        new_physics_steps_in_certification=0,strict_held_walking_m=measure['strict_held_base_net_displacement_m'],
        forward_held_walking_m=measure['strict_held_base_forward_displacement_m'],goal_error_m=measure['goal_error_m'],
        final_cup_upright_cosine=measure['final_cup_upright_cosine'],carry_foot_cycles=measure['carry_foot_cycles'],
        new_native_steps_this_six_hour_run=18360,cumulative_native_steps=total,costs=costs,
        successful_control_condition=dict(original_geometry_mass_friction_PD_effort_unchanged=True,
            explicit_numerical_change='NoSlip3 from physical step3960, preserved in replay and audit',
            loaded_finger_reference_ratio=positive['loaded_native_reference_ratio'],original_halfclosed_reference_condition_not_claimed=True,
            grasp_reference='Original R3 equilibrium opposing grasp; lowered-body variants failed and were not used.',
            task_control_changes=['Wait for unchanged actual6mm load-transfer gates','Stationary G1 reference after release/retract'],
            trained_groot_connected=False,online_replanning_active=False,
            inherited_body_plan_protocol_field_not_used_by_successful_task=True),
        qualified_full_episodes=1,physical_trial_branches=6,engineering_startup_failures=1,
        independently_sampled_scenes=1,independent_success_rate_not_estimated=True,
        training_learning_effect_not_evaluated=True,dataset_split='unassigned',source_role='development_validation',
        branches=branches,old75000_step_cap_explicitly_superseded_by_user=True,
        all_required_work_for_current_full_task_complete=True)
    out=root/'FINAL_REVIEW.json';assert not out.exists();safe_save(out,result)
    print(dict(certified=True,review=str(out),strict_held_m=measure['strict_held_base_net_displacement_m'],native_total=total,qualified=1),flush=True)


if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--report',type=Path,required=True)
    a=ap.parse_args();run(a.root,a.report)
