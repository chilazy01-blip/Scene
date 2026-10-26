import math

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_native_dynamic_shadow import (
    build_dynamic_g1_encoder_blocks,
    merge_planner_replan,
    official_control_arrays,
)


def _qpos(rows: int, offset: float = 0.0):
    values = np.zeros((rows, 36), dtype=np.float64)
    values[:, 0] = offset + np.arange(rows)
    values[:, 2] = 0.788740
    values[:, 3] = 1.0
    values[:, 7:] = offset + np.arange(rows)[:, None]
    return values


def _yaw_quaternion(yaw: float):
    return np.asarray(
        [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)],
        dtype=np.float64,
    )


def test_replan_merge_rebases_and_uses_exact_eight_tick_crossfade():
    old = _qpos(73)
    generated = _qpos(73, offset=100.0)
    merged = merge_planner_replan(old, generated, current_frame=50, generation_frame=52)
    assert merged.shape == (75, 36)
    assert merged[0, 0] == pytest.approx(old[50, 0])
    assert merged[2, 0] == pytest.approx(old[52, 0])
    assert merged[6, 0] == pytest.approx(0.5 * old[56, 0] + 0.5 * generated[4, 0])
    assert merged[10, 0] == pytest.approx(generated[8, 0])
    assert merged[-1, 0] == pytest.approx(generated[-1, 0])


def test_dynamic_encoder_uses_actual_heading_but_keeps_inactive_blocks_zero():
    reference = _qpos(60)
    reference[:, 0] *= 0.01
    reference[:, 7:] *= 0.001
    velocities = np.zeros((60, 29), dtype=np.float64)
    aligned = build_dynamic_g1_encoder_blocks(
        reference,
        velocities,
        0,
        initial_robot_quaternion_wxyz=_yaw_quaternion(math.pi / 2),
        current_robot_quaternion_wxyz=_yaw_quaternion(math.pi / 2),
    )
    turned = build_dynamic_g1_encoder_blocks(
        reference,
        velocities,
        0,
        initial_robot_quaternion_wxyz=_yaw_quaternion(math.pi / 2),
        current_robot_quaternion_wxyz=_yaw_quaternion(math.pi),
    )
    assert aligned["motion_anchor_orientation_heading_10frame_step5"].shape == (60,)
    assert not np.array_equal(
        aligned["motion_anchor_orientation_heading_10frame_step5"],
        turned["motion_anchor_orientation_heading_10frame_step5"],
    )
    assert np.count_nonzero(aligned["smpl_joints_10frame_step1"]) == 0
    assert aligned["encoder_mode_4"].tolist() == [0.0, 0.0, 0.0, 0.0]


def test_dynamic_encoder_rejects_an_incomplete_future_window():
    with pytest.raises(ValueError, match="complete finite reference window"):
        build_dynamic_g1_encoder_blocks(
            _qpos(45),
            np.zeros((45, 29)),
            0,
            initial_robot_quaternion_wxyz=[1.0, 0.0, 0.0, 0.0],
            current_robot_quaternion_wxyz=[1.0, 0.0, 0.0, 0.0],
        )


def test_official_control_arrays_have_29_positive_bounded_entries():
    controls = official_control_arrays()
    assert set(controls) == {"armature", "kp", "kd", "effort_limit"}
    assert all(len(values) == 29 for values in controls.values())
    assert all(value > 0 for values in controls.values() for value in values)
    assert controls["armature"][4] == pytest.approx(2.0 * controls["armature"][15])
    assert controls["effort_limit"][3] == 139.0
    assert controls["effort_limit"][20] == 5.0
