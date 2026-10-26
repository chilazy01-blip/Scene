from dataclasses import replace

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_causal_hold_shadow import (
    build_causal_hold_encoder_blocks,
    verify_prefix_equivalence,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.tests.test_sonic_offline_observation_mapper import (
    fake_inputs,
)


def test_causal_hold_repeats_current_command_and_zeroes_reference_velocity():
    inputs = fake_inputs()
    index = 11
    blocks = build_causal_hold_encoder_blocks(inputs, index)
    positions = blocks["motion_joint_positions_10frame_step5"].reshape(10, 29)
    velocities = blocks["motion_joint_velocities_10frame_step5"].reshape(10, 29)
    expected = reorder_mujoco_to_isaaclab(inputs.source_targets_mujoco_rad[index])
    assert np.array_equal(positions, np.repeat(expected[None, :], 10, axis=0))
    assert np.count_nonzero(velocities) == 0


def test_causal_hold_uses_current_root_for_all_anchor_rows():
    inputs = fake_inputs()
    blocks = build_causal_hold_encoder_blocks(inputs, 7)
    anchors = blocks["motion_anchor_orientation_heading_10frame_step5"].reshape(10, 6)
    assert np.array_equal(anchors, np.repeat(anchors[:1], 10, axis=0))
    assert anchors[0].tolist() == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_mutating_every_future_row_cannot_change_current_encoder_input():
    inputs = fake_inputs()
    index = 12
    baseline = build_causal_hold_encoder_blocks(inputs, index)
    position = inputs.body_position_mujoco_rad.copy()
    velocity = inputs.body_velocity_mujoco_rad_s.copy()
    quaternion = inputs.base_quaternion_wxyz.copy()
    angular = inputs.base_angular_velocity_rad_s.copy()
    targets = inputs.source_targets_mujoco_rad.copy()
    position[index + 1 :] = 123.0
    velocity[index + 1 :] = -456.0
    quaternion[index + 1 :] = [0.0, 1.0, 0.0, 0.0]
    angular[index + 1 :] = 789.0
    targets[index + 1 :] = -987.0
    mutated = replace(
        inputs,
        body_position_mujoco_rad=position,
        body_velocity_mujoco_rad_s=velocity,
        base_quaternion_wxyz=quaternion,
        base_angular_velocity_rad_s=angular,
        source_targets_mujoco_rad=targets,
    )
    candidate = build_causal_hold_encoder_blocks(mutated, index)
    assert baseline.keys() == candidate.keys()
    for name in baseline:
        assert np.array_equal(baseline[name], candidate[name]), name


def test_prefix_only_and_full_stream_observations_are_exactly_equal():
    proof = verify_prefix_equivalence(fake_inputs(rows=64))
    assert proof["all_equal"] is True
    assert proof["probe_count"] == 6
    assert all(row["encoder_equal"] for row in proof["probes"])
    assert all(row["decoder_equal"] for row in proof["probes"])


def test_causal_hold_accepts_last_sample_and_rejects_out_of_range():
    inputs = fake_inputs()
    build_causal_hold_encoder_blocks(inputs, inputs.sample_count - 1)
    with pytest.raises(ValueError, match="invalid"):
        build_causal_hold_encoder_blocks(inputs, inputs.sample_count)
