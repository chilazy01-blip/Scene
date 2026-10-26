import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _body_angular_velocity,
    mapping_inputs_from_planner_qpos,
)


def _qpos(rows: int = 60):
    values = np.zeros((rows, 36), dtype=np.float64)
    values[:, 2] = 0.788740
    values[:, 3] = 1.0
    values[:, 7] = np.arange(rows) * 0.01
    return values


def test_planner_qpos_becomes_complete_policy_state_without_source_orders():
    inputs = mapping_inputs_from_planner_qpos(_qpos())
    assert inputs.sample_count == 60
    assert inputs.body_position_mujoco_rad.shape == (60, 29)
    assert inputs.body_velocity_mujoco_rad_s[0, 0] == pytest.approx(0.5)
    assert np.array_equal(
        inputs.source_targets_mujoco_rad, inputs.body_position_mujoco_rad
    )
    assert inputs.source_model_joint_order == ()
    assert inputs.source_actuator_order == ()


def test_body_angular_velocity_is_zero_for_fixed_orientation():
    quaternions = np.zeros((10, 4), dtype=np.float64)
    quaternions[:, 0] = 1.0
    assert np.array_equal(_body_angular_velocity(quaternions), np.zeros((10, 3)))


def test_body_angular_velocity_recovers_constant_yaw_rate():
    times = np.arange(10) * 0.02
    yaw = 0.4 * times
    quaternions = np.column_stack(
        [np.cos(yaw / 2.0), np.zeros(10), np.zeros(10), np.sin(yaw / 2.0)]
    )
    velocity = _body_angular_velocity(quaternions)
    assert velocity[:, 2] == pytest.approx(0.4, abs=1e-10)


def test_planner_qpos_rejects_short_or_nonfinite_stream():
    with pytest.raises(ValueError, match="future window"):
        mapping_inputs_from_planner_qpos(_qpos(45))
    invalid = _qpos()
    invalid[20, 4] = np.nan
    with pytest.raises(ValueError, match="future window"):
        mapping_inputs_from_planner_qpos(invalid)
