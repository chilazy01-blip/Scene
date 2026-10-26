from dataclasses import replace

import numpy as np

from sage.experiments.embodied_data_stability_v1.sonic_causal_motion_reference import (
    FRAME_OFFSETS,
    G1_LOOKAHEAD_TICKS,
    OnlineCausalReferenceBuilder,
    build_causal_reference_stream,
    build_motion_encoder_blocks,
    evaluate_motion_takeover_screen,
    evaluate_reference_integrity,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    MappingInputs,
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)


def fake_inputs(rows: int = 140) -> MappingInputs:
    times = np.arange(rows, dtype=np.float64) * 0.02
    phase = np.arange(29, dtype=np.float64)[None, :] * 0.07
    position = np.asarray(DEFAULT_ANGLES)[None, :] + 0.04 * np.sin(
        np.arange(rows, dtype=np.float64)[:, None] * 0.2 + phase
    )
    velocity = np.gradient(position, 0.02, axis=0)
    quaternion = np.zeros((rows, 4), dtype=np.float64)
    quaternion[:, 0] = 1.0
    return MappingInputs(
        times_s=times,
        body_position_mujoco_rad=position,
        body_velocity_mujoco_rad_s=velocity,
        base_quaternion_wxyz=quaternion,
        base_angular_velocity_rad_s=np.zeros((rows, 3), dtype=np.float64),
        source_targets_mujoco_rad=position + 0.01,
        phase_events=(
            {"phase": "approach", "sim_time_s": 0.0, "source_event": "test"},
        ),
        source_model_joint_order=SONIC_BODY_JOINT_ORDER,
        source_actuator_order=SONIC_BODY_JOINT_ORDER,
    )


def test_analog_continuations_never_extend_past_current_tick():
    inputs = fake_inputs()
    reference = build_causal_reference_stream(
        inputs, np.zeros(inputs.sample_count, dtype=np.int64)
    )
    assert not reference.analog_available[G1_LOOKAHEAD_TICKS]
    assert reference.analog_available[G1_LOOKAHEAD_TICKS + 10]
    assert np.all(
        reference.maximum_consumed_state_index
        <= np.arange(inputs.sample_count, dtype=np.int64)
    )
    for index in np.flatnonzero(reference.analog_available):
        selected = reference.neighbor_indices[index]
        selected = selected[selected >= 0]
        assert selected.size
        assert int(selected.max()) + G1_LOOKAHEAD_TICKS <= index


def test_incremental_builder_is_exactly_the_batch_builder():
    inputs = fake_inputs()
    actions = np.zeros(inputs.sample_count, dtype=np.int64)
    batch = build_causal_reference_stream(inputs, actions)
    online = OnlineCausalReferenceBuilder()
    for index in range(inputs.sample_count):
        tick = online.append(
            position_mujoco_rad=inputs.body_position_mujoco_rad[index],
            velocity_mujoco_rad_s=inputs.body_velocity_mujoco_rad_s[index],
            source_target_mujoco_rad=inputs.source_targets_mujoco_rad[index],
            phase="approach",
            high_level_action_index=0,
        )
        assert np.array_equal(
            tick.positions_mujoco_rad, batch.positions_mujoco_rad[index]
        )
        assert np.array_equal(
            tick.velocities_mujoco_rad_s,
            batch.velocities_mujoco_rad_s[index],
        )
        assert tick.analog_available == bool(batch.analog_available[index])
        assert tick.maximum_consumed_state_index == int(
            batch.maximum_consumed_state_index[index]
        )


def test_future_mutation_cannot_change_existing_reference_prefix():
    inputs = fake_inputs()
    actions = np.zeros(inputs.sample_count, dtype=np.int64)
    original = build_causal_reference_stream(inputs, actions)
    cutoff = 90
    mutated = MappingInputs(
        times_s=inputs.times_s.copy(),
        body_position_mujoco_rad=inputs.body_position_mujoco_rad.copy(),
        body_velocity_mujoco_rad_s=inputs.body_velocity_mujoco_rad_s.copy(),
        base_quaternion_wxyz=inputs.base_quaternion_wxyz.copy(),
        base_angular_velocity_rad_s=inputs.base_angular_velocity_rad_s.copy(),
        source_targets_mujoco_rad=inputs.source_targets_mujoco_rad.copy(),
        phase_events=inputs.phase_events,
        source_model_joint_order=inputs.source_model_joint_order,
        source_actuator_order=inputs.source_actuator_order,
    )
    mutated.body_position_mujoco_rad[cutoff + 1 :] += 100.0
    mutated.body_velocity_mujoco_rad_s[cutoff + 1 :] -= 100.0
    mutated.source_targets_mujoco_rad[cutoff + 1 :] *= -50.0
    changed = build_causal_reference_stream(mutated, actions)
    assert np.array_equal(
        original.positions_mujoco_rad[: cutoff + 1],
        changed.positions_mujoco_rad[: cutoff + 1],
    )
    assert np.array_equal(
        original.velocities_mujoco_rad_s[: cutoff + 1],
        changed.velocities_mujoco_rad_s[: cutoff + 1],
    )


def test_task_or_action_boundary_resets_to_hold_until_new_history_exists():
    inputs = fake_inputs()
    actions = np.zeros(inputs.sample_count, dtype=np.int64)
    actions[80:] = 1
    reference = build_causal_reference_stream(inputs, actions)
    assert reference.analog_available[79]
    assert not reference.analog_available[80]
    assert not reference.analog_available[80 + G1_LOOKAHEAD_TICKS + 9]
    assert reference.analog_available[80 + G1_LOOKAHEAD_TICKS + 10]
    held = reference.positions_mujoco_rad[80]
    assert np.all(held == inputs.body_position_mujoco_rad[80][None, :])


def test_motion_encoder_uses_ten_causal_frames_in_official_joint_order():
    inputs = fake_inputs()
    reference = build_causal_reference_stream(
        inputs, np.zeros(inputs.sample_count, dtype=np.int64)
    )
    index = 75
    blocks = build_motion_encoder_blocks(inputs, reference, index)
    assert len(ENCODER_ASSEMBLER.assemble(blocks)) == 1751
    positions = blocks["motion_joint_positions_10frame_step5"].reshape(10, 29)
    velocities = blocks["motion_joint_velocities_10frame_step5"].reshape(10, 29)
    assert FRAME_OFFSETS == tuple(range(0, 46, 5))
    assert np.array_equal(
        positions[0],
        reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[index]),
    )
    assert np.array_equal(
        velocities[0],
        reorder_mujoco_to_isaaclab(inputs.body_velocity_mujoco_rad_s[index]),
    )


def test_reference_integrity_is_fail_closed_and_does_not_clip():
    inputs = fake_inputs()
    reference = build_causal_reference_stream(
        inputs, np.zeros(inputs.sample_count, dtype=np.int64)
    )
    gate = {
        "allowed_global_max_abs_delta_rad": 10.0,
        "allowed_command_envelope": {
            "admission_lower_rad": [-10.0] * 29,
            "admission_upper_rad": [10.0] * 29,
        },
    }
    report = evaluate_reference_integrity(reference, gate)
    assert report["passed"]
    assert report["no_output_clipping_or_rate_limiting"]
    assert report["maximum_consumed_minus_current_offset"] == 0


def test_motion_takeover_requires_non_hold_reference_for_full_qualification():
    inputs = fake_inputs()
    reference = build_causal_reference_stream(
        inputs, np.zeros(inputs.sample_count, dtype=np.int64)
    )
    moving_positions = reference.positions_mujoco_rad.copy()
    moving_positions[55:, -1, 0] += 0.1
    moving = replace(reference, positions_mujoco_rad=moving_positions)
    gate = {
        "allowed_global_max_abs_delta_rad": 10.0,
        "allowed_command_envelope": {
            "admission_lower_rad": [-10.0] * 29,
            "admission_upper_rad": [10.0] * 29,
        },
    }
    safe_targets = np.zeros((inputs.sample_count, 29), dtype=np.float64)
    report = evaluate_motion_takeover_screen(
        targets=safe_targets,
        inputs=inputs,
        reference=moving,
        gate=gate,
    )
    assert report["passed"]
    held = replace(
        reference,
        positions_mujoco_rad=np.repeat(
            inputs.body_position_mujoco_rad[:, None, :], 10, axis=1
        ),
    )
    held_report = evaluate_motion_takeover_screen(
        targets=safe_targets,
        inputs=inputs,
        reference=held,
        gate=gate,
    )
    assert not held_report["passed"]
