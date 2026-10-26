"""Collect completed negative branches without integrating physics or altering evidence."""
import argparse
import hashlib
import json
import resource
import os
from pathlib import Path
from datetime import datetime, timezone


def binding(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return dict(path=str(path.resolve()), sha256=h.hexdigest(), size_bytes=path.stat().st_size)


def read(path):
    return json.loads(Path(path).read_text())


def check(item):
    assert binding(item['path']) == item, item['path']


def run(root):
    baseline = read(root / 'INTEGRATION_PROTOCOL.json')
    approval = read(root / 'APPROVED_TIME_WINDOW.json')
    ledger_path = Path(baseline['ledger_root']) / 'COST.json'
    ledger = read(ledger_path)
    assert approval['cumulative_native_cap'] == baseline['cumulative_native_cap'] == 75000
    assert datetime.now(timezone.utc).timestamp() >= approval['deadline_epoch_utc']
    total = ledger['prior_native_steps']
    costs = []
    for reservation in ledger['reservations']:
        path = Path(reservation['output']) / 'REPORT.json'
        result = read(path)  # An unfinished reservation is an error, never zero cost.
        steps = result['physics_steps']
        assert 0 <= steps <= reservation['maximum_steps']
        total += steps
        costs.append(dict(report=binding(path), actual_new_steps=steps))
    numbers = [18, 19, 20, 21, 22, 24, 25, 26, 27, 28]
    branches = []
    for number in numbers:
        folder = root / f'attempt_{number}'
        files = dict(report=folder/'full/REPORT.json', audit=folder/'full/AUDIT.json',
                     cost=folder/'cost/REPORT.json', force=folder/'FORCE_CHECK.json',
                     video=folder/'diagnostic_video/MANIFEST.json',
                     detail=folder/'grasp_detail/MANIFEST.json',
                     delivery=folder/'partial_delivery/REVIEW.json')
        data = {key: read(path) for key, path in files.items()}
        r, a, c, f, v, d = (data[key] for key in ['report','audit','cost','force','video','delivery'])
        assert not r['task_passed'] and r['stop_reason'] == 'object_slipped'
        assert a['executed_control_reconstruction_passed']
        failed = [key for key, value in a['gates'].items() if not value]
        assert failed == ['bounded_complete_episode'], failed
        assert a['report'] == c['episode_report'] == v['report'] == d['report'] == binding(files['report'])
        for item in [r['engine'], r['protocol'], r['case'], r['model'], a['implementation']]:
            check(item)
        assert a['new_physics_steps'] == f['new_physics_steps'] == v['new_physics_steps'] == data['detail']['new_physics_steps'] == 0
        assert a['max_pd_error_nm'] == a['max_contact_error'] == a['max_geometry_error_m'] == 0
        assert f['maximum_hand_and_desk_force_error_n'] < 1e-12
        assert d['all_decoded_frames'] == v['frames'] == r['physics_steps'] // 4
        assert not d['mechanically_qualified'] and d['positive_episode_count'] == 0
        assert not (folder/'delivery/episode.npz').exists()
        assert c['physics_steps'] + c['prefix_already_charged_steps'] == r['physics_steps']
        # All these contact sheets have been inspected by the primary agent.
        # Full-frame review is automated decoding, not manual inspection of every frame.
        pictures = [folder/'grasp_detail/review.jpg', folder/'partial_delivery/decoded_review.jpg']
        branches.append(dict(number=number, artifacts={key:binding(path) for key,path in files.items()},
            primary_agent_visual_review=dict(contact_sheets=[binding(path) for path in pictures],
                every_frame_manually_viewed=False, task_complete=False),
            new_physics_steps=c['physics_steps'], archived_total_steps=r['physics_steps'],
            stage=r['stage'], stop_reason=r['stop_reason'], original_task_gates=r['gates'],
            carry_distance_m=r['carry_distance_m'], carry_foot_cycles=r['carry_foot_cycles'],
            max_held_slip_m=r['max_held_slip_m'], failed_audit_gates=failed,
            decoded_frames=d['all_decoded_frames'],
            changed_reference_envelope=r.get('different_control_regime_from_halfclosed_baseline', False)))
    added = sum(branch['new_physics_steps'] for branch in branches)
    assert added == 5088 and total == 66204 and total - added == 61116
    assert not (root/'attempt_23/full/REPORT.json').exists()
    result = dict(schema='sonic-approved-resume-review/v1',
        created_utc=datetime.now(timezone.utc).isoformat(), implementation=binding(__file__),
        approval=binding(root/'APPROVED_TIME_WINDOW.json'), ledger=binding(ledger_path), costs=costs,
        prior_to_this_window_native_steps=total-added, this_window_new_physics_steps=added,
        cumulative_native_steps=total, cumulative_cap=75000, remaining_native_steps=75000-total,
        exit_reason='approved_two_hour_physics_window_expired', native_step_cap_exhausted=False,
        new_physics_steps_in_this_review=0, actual_continuation_branches=len(branches),
        qualified_full_task_episodes=0, independently_sampled_scenes=1,
        shared_prefix_reuse_is_not_independent_grasp_success=True, training_learning_effect_not_evaluated=True,
        best_carry_m=max(branch['carry_distance_m'] for branch in branches),
        physical_model_PD_effort_friction_joint_limits_and_task_acceptance_unchanged=True,
        reference_envelope_065_is_a_separate_control_regime=True,
        trained_groot_connected=False, online_replanning_active=False,
        positive_continuous_physics_replay_performed=False,
        original_task_incomplete=True, all_negative_branches_postprocessed=True, branches=branches)
    output = root/'APPROVED_RESUME_REVIEW.json'
    assert not output.exists(), output
    result['content_sha256_excluding_this_field'] = hashlib.sha256(
        json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    output.write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+'\n')
    print(dict(review=str(output), added=added, cumulative=total, remaining=75000-total,
               branches=len(branches), positives=0, best_carry_m=result['best_carry_m']), flush=True)


if __name__ == '__main__':
    resource.setrlimit(resource.RLIMIT_AS, (16*1024**3, 16*1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root)
