from pathlib import Path

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    G1_LOOKAHEAD_TICKS,
    MUJOCO_TO_ISAACLAB,
    MappingInputs,
    _rotation_6d_rowwise,
    _xml_joint_and_actuator_order,
    build_decoder_blocks,
    build_g1_encoder_blocks,
    gravity_direction,
    history_window,
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    ISAACLAB_TO_MUJOCO,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)


def fake_inputs(rows=64):
    times = np.arange(1, rows + 1, dtype=np.float64) * 0.02
    position = np.repeat(np.asarray(DEFAULT_ANGLES)[None, :], rows, axis=0)
    position += np.arange(rows, dtype=np.float64)[:, None] * 0.001
    velocity = np.repeat(np.arange(29, dtype=np.float64)[None, :], rows, axis=0)
    quaternion = np.zeros((rows, 4), dtype=np.float64)
    quaternion[:, 0] = 1.0
    angular = np.column_stack(
        (np.arange(rows), np.arange(rows) + 1, np.arange(rows) + 2)
    ).astype(np.float64)
    return MappingInputs(
        times_s=times,
        body_position_mujoco_rad=position,
        body_velocity_mujoco_rad_s=velocity,
        base_quaternion_wxyz=quaternion,
        base_angular_velocity_rad_s=angular,
        source_targets_mujoco_rad=position.copy(),
        phase_events=(),
        source_model_joint_order=SONIC_BODY_JOINT_ORDER,
        source_actuator_order=SONIC_BODY_JOINT_ORDER,
    )


def test_mapping_inverse_and_default_relative_position():
    assert tuple(
        ISAACLAB_TO_MUJOCO[mujoco_index] for mujoco_index in MUJOCO_TO_ISAACLAB
    ) == tuple(range(29))
    mujoco = np.arange(29, dtype=np.float64)
    isaac = reorder_mujoco_to_isaaclab(mujoco)
    for mujoco_index, isaac_index in enumerate(ISAACLAB_TO_MUJOCO):
        assert isaac[isaac_index] == mujoco[mujoco_index]


def test_history_matches_official_oldest_first_leading_zero_padding():
    values = np.asarray([[1.0], [2.0], [3.0]])
    assert history_window(values, 0, frames=3).reshape(-1).tolist() == [0.0, 0.0, 1.0]
    assert history_window(values, 2, frames=3).reshape(-1).tolist() == [1.0, 2.0, 3.0]
    with pytest.raises(ValueError, match="invalid"):
        history_window(values, 3, frames=3)


def test_gravity_and_rotation_6d_identity_conventions():
    identity = np.asarray([1.0, 0.0, 0.0, 0.0])
    assert gravity_direction(identity).tolist() == [0.0, 0.0, -1.0]
    assert _rotation_6d_rowwise(identity).tolist() == [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]


def test_g1_mode_fills_only_official_required_blocks_with_real_future():
    inputs = fake_inputs()
    blocks = build_g1_encoder_blocks(inputs, 0)
    assert len(ENCODER_ASSEMBLER.assemble(blocks)) == 1751
    assert blocks["encoder_mode_4"].tolist() == [0.0, 0.0, 0.0, 0.0]
    assert np.count_nonzero(blocks["smpl_joints_10frame_step1"]) == 0
    positions = blocks["motion_joint_positions_10frame_step5"].reshape(10, 29)
    assert (
        positions[0].tolist()
        == reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[0]).tolist()
    )
    assert (
        positions[1].tolist()
        == reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[5]).tolist()
    )
    with pytest.raises(ValueError, match="45 real future ticks"):
        build_g1_encoder_blocks(inputs, inputs.sample_count - G1_LOOKAHEAD_TICKS)


def test_decoder_history_uses_relative_joint_positions_and_autoregressive_actions():
    inputs = fake_inputs()
    actions = np.zeros((inputs.sample_count, 29), dtype=np.float64)
    actions[1] = 2.0
    blocks = build_decoder_blocks(
        inputs,
        1,
        token_state=np.arange(64, dtype=np.float64),
        logged_last_actions_isaaclab=actions,
    )
    assert len(DECODER_ASSEMBLER.assemble(blocks)) == 994
    positions = blocks["his_body_joint_positions_10frame_step1"].reshape(10, 29)
    assert np.count_nonzero(positions[:-2]) == 0
    assert np.allclose(positions[-2], 0.0)
    assert np.allclose(positions[-1], 0.001)
    action_history = blocks["his_last_actions_10frame_step1"].reshape(10, 29)
    assert np.all(action_history[-2] == 0.0)
    assert np.all(action_history[-1] == 2.0)


def test_xml_order_parser_keeps_model_and_actuator_orders_separate(tmp_path: Path):
    path = tmp_path / "robot.xml"
    path.write_text(
        """<mujoco><worldbody><body><joint name="body_a"/>"
        "<joint name="finger"/><joint name="body_b"/></body></worldbody>"
        "<actuator><position joint="body_a"/><position joint="body_b"/>"
        "<position joint="finger"/></actuator></mujoco>""",
        encoding="utf-8",
    )
    joints, actuators = _xml_joint_and_actuator_order(path)
    assert joints == ("body_a", "finger", "body_b")
    assert actuators == ("body_a", "body_b", "finger")
