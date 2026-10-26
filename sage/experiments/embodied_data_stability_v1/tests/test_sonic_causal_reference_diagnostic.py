import numpy as np
from types import SimpleNamespace

from sage.experiments.embodied_data_stability_v1.sonic_causal_reference_diagnostic import (
    _block_delta,
    build_causal_damped_state_projection_encoder_blocks,
    build_causal_measured_state_hold_encoder_blocks,
    build_causal_measured_state_mean10_hold_encoder_blocks,
    build_source_applied_action_history,
    continuity_metrics,
    evaluate_one_step_takeover_screen,
    evaluate_non_regression_gate,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    G1_FUTURE_FRAMES,
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ACTION_SCALES,
    DEFAULT_ANGLES,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)


def fake_gate(global_max=0.5, p99_9=0.5):
    return {
        "allowed_global_max_abs_delta_rad": global_max,
        "allowed_p99_9_abs_delta_rad": p99_9,
        "allowed_command_envelope": {
            "admission_lower_rad": [-2.0] * 29,
            "admission_upper_rad": [2.0] * 29,
        },
    }


def fake_inputs():
    rows = 4
    position = np.arange(rows * 29, dtype=np.float64).reshape(rows, 29) * 0.001
    velocity = np.arange(rows * 29, dtype=np.float64).reshape(rows, 29) * 0.01
    return SimpleNamespace(
        sample_count=rows,
        body_position_mujoco_rad=position,
        body_velocity_mujoco_rad_s=velocity,
        source_targets_mujoco_rad=np.zeros((rows, 29), dtype=np.float64),
        base_quaternion_wxyz=np.tile(np.asarray([1.0, 0.0, 0.0, 0.0]), (rows, 1)),
    )


def test_continuity_reports_exact_worst_transition_and_joint():
    values = np.zeros((4, 29), dtype=np.float64)
    values[2, 7] = 0.75
    result = continuity_metrics(values)
    assert result["global_max_abs_delta_rad"] == 0.75
    assert result["global_max_transition"] == {
        "from_sample_index": 1,
        "to_sample_index": 2,
        "joint_index": 7,
        "joint_name": SONIC_BODY_JOINT_ORDER[7],
        "signed_delta_rad": 0.75,
    }


def test_non_regression_gate_does_not_clip_and_rejects_large_slew():
    values = np.zeros((3, 29), dtype=np.float64)
    values[1, 4] = 0.8
    original = values.copy()
    result = evaluate_non_regression_gate(values, fake_gate())
    assert result["passed"] is False
    assert result["checks"]["global_max_slew_not_worse_than_source"] is False
    assert np.array_equal(values, original)


def test_non_regression_gate_rejects_command_envelope_violation():
    values = np.zeros((3, 29), dtype=np.float64)
    values[:, 12] = 2.5
    values[1, 13] = -2.25
    result = evaluate_non_regression_gate(values, fake_gate(global_max=3.0, p99_9=3.0))
    assert result["passed"] is False
    assert result["command_envelope_violation_count"] == 4
    assert result["first_command_envelope_violations"][0]["joint_index"] == 12
    by_joint = result["command_envelope_by_joint"]
    assert by_joint[12] == {
        "joint_index": 12,
        "joint_name": SONIC_BODY_JOINT_ORDER[12],
        "violation_count": 3,
        "candidate_min_rad": 2.5,
        "candidate_max_rad": 2.5,
        "admission_lower_rad": -2.0,
        "admission_upper_rad": 2.0,
        "max_below_excess_rad": 0.0,
        "max_above_excess_rad": 0.5,
    }
    assert by_joint[13]["violation_count"] == 1
    assert by_joint[13]["max_below_excess_rad"] == 0.25
    assert by_joint[13]["max_above_excess_rad"] == 0.0


def test_block_delta_attributes_each_named_input_independently():
    previous = {"a": np.asarray([0.0, 1.0]), "b": np.asarray([3.0])}
    current = {"a": np.asarray([2.0, 1.0]), "b": np.asarray([4.0])}
    result = _block_delta(previous, current)
    assert result["a"] == {"l_inf": 2.0, "l2": 2.0, "nonzero": 1}
    assert result["b"] == {"l_inf": 1.0, "l2": 1.0, "nonzero": 1}


def test_measured_state_hold_repeats_current_measurement_not_source_target():
    inputs = fake_inputs()
    blocks = build_causal_measured_state_hold_encoder_blocks(inputs, 2)
    positions = blocks["motion_joint_positions_10frame_step5"].reshape(
        G1_FUTURE_FRAMES, 29
    )
    velocities = blocks["motion_joint_velocities_10frame_step5"].reshape(
        G1_FUTURE_FRAMES, 29
    )
    expected = reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[2])
    assert np.array_equal(positions, np.repeat(expected[None, :], 10, axis=0))
    assert np.array_equal(velocities, np.zeros((10, 29)))


def test_damped_projection_uses_only_current_and_past_rows():
    inputs = fake_inputs()
    original = build_causal_damped_state_projection_encoder_blocks(inputs, 2)
    mutated = fake_inputs()
    mutated.body_position_mujoco_rad[3] = 999.0
    mutated.body_velocity_mujoco_rad_s[3] = 999.0
    mutated.source_targets_mujoco_rad[3] = 999.0
    mutated.base_quaternion_wxyz[3] = [0.0, 0.0, 0.0, 1.0]
    changed = build_causal_damped_state_projection_encoder_blocks(mutated, 2)
    for name in original:
        assert np.array_equal(original[name], changed[name])

    positions = original["motion_joint_positions_10frame_step5"].reshape(10, 29)
    velocities = original["motion_joint_velocities_10frame_step5"].reshape(10, 29)
    current = reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[2])
    mean_velocity = reorder_mujoco_to_isaaclab(
        inputs.body_velocity_mujoco_rad_s[:3].mean(axis=0)
    )
    assert np.array_equal(positions[0], current)
    assert np.array_equal(velocities[0], mean_velocity)
    assert np.all(np.abs(velocities[-1]) < np.abs(mean_velocity))


def test_mean10_hold_uses_available_prefix_and_ignores_future_rows():
    inputs = fake_inputs()
    original = build_causal_measured_state_mean10_hold_encoder_blocks(inputs, 2)
    mutated = fake_inputs()
    mutated.body_position_mujoco_rad[3] = 999.0
    changed = build_causal_measured_state_mean10_hold_encoder_blocks(mutated, 2)
    for name in original:
        assert np.array_equal(original[name], changed[name])

    positions = original["motion_joint_positions_10frame_step5"].reshape(10, 29)
    expected = reorder_mujoco_to_isaaclab(
        inputs.body_position_mujoco_rad[:3].mean(axis=0)
    )
    assert np.allclose(positions, np.repeat(expected[None, :], 10, axis=0))


def test_source_applied_history_is_one_tick_delayed_and_inverts_action_transform():
    inputs = fake_inputs()
    inputs.source_targets_mujoco_rad = (
        np.asarray(DEFAULT_ANGLES)[None, :]
        + np.arange(4, dtype=np.float64)[:, None] * np.asarray(ACTION_SCALES)[None, :]
    )
    history = build_source_applied_action_history(inputs, 4)
    assert np.array_equal(history[0], np.zeros(29))
    assert np.allclose(history[1], np.zeros(29))
    assert np.allclose(history[2], np.ones(29))
    assert np.allclose(history[3], np.full(29, 2.0))


def test_one_step_takeover_screen_requires_a_full_qualification_window():
    source = np.zeros((55, 29), dtype=np.float64)
    targets = np.zeros_like(source)
    result = evaluate_one_step_takeover_screen(
        targets,
        source,
        np.arange(55, dtype=np.float64) * 0.02,
        fake_gate(),
        qualification_ticks=50,
    )
    assert result["passed"] is True
    assert result["eligible_sample_count"] == 54
    assert result["longest_eligible_run_ticks"] == 54
    assert result["first_20_qualifying_windows"][0]["start_sample_index"] == 1


def test_one_step_takeover_screen_breaks_on_slew_or_envelope_failure():
    source = np.zeros((8, 29), dtype=np.float64)
    targets = np.zeros_like(source)
    targets[3, 0] = 0.75
    targets[6, 1] = 2.5
    result = evaluate_one_step_takeover_screen(
        targets,
        source,
        np.arange(8, dtype=np.float64) * 0.02,
        fake_gate(),
        qualification_ticks=4,
    )
    assert result["passed"] is False
    assert result["ineligible_handoff_slew_sample_count"] == 2
    assert result["ineligible_envelope_sample_count"] == 1
    assert result["longest_eligible_run_ticks"] == 2
