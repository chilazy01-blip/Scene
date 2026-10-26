import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK,
    DEFAULT_ANGLES,
    build_planner_inputs,
    context_from_motion_50hz,
    initialize_context,
    resample_qpos_50hz,
    validate_planner_outputs,
)


def _valid_output(frames: int = 36):
    qpos = np.zeros((1, 64, 36), dtype=np.float32)
    qpos[0, :, 2] = 0.788740
    qpos[0, :, 3] = 1.0
    qpos[0, :, 7:] = np.asarray(DEFAULT_ANGLES, dtype=np.float32)
    return qpos, np.asarray([frames], dtype=np.int32)


def test_initial_context_matches_official_standing_contract():
    context = initialize_context()
    assert context.shape == (1, 4, 36)
    assert context.dtype == np.float32
    assert np.array_equal(context[0, 0], context[0, 3])
    assert context[0, 0, 2] == pytest.approx(0.788740)
    assert context[0, 0, 3:7].tolist() == [1.0, 0.0, 0.0, 0.0]
    assert context[0, 0, 7:].tolist() == pytest.approx(DEFAULT_ANGLES)


def test_planner_inputs_use_active_deployment_mask_and_exact_dtypes():
    inputs = build_planner_inputs(
        initialize_context(),
        mode=2,
        movement_direction=(1.0, 0.0, 0.0),
    )
    assert inputs["context_mujoco_qpos"].shape == (1, 4, 36)
    assert inputs["mode"].dtype == np.int64
    assert inputs["movement_direction"].dtype == np.float32
    assert inputs["has_specific_target"].shape == (1, 1)
    assert inputs["allowed_pred_num_tokens"].tolist() == [
        list(ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK)
    ]


def test_output_validation_slices_prefix_and_rejects_wrong_frame_count():
    qpos, count = _valid_output(36)
    valid, frame_count, metrics = validate_planner_outputs(qpos, count)
    assert valid.shape == (36, 36)
    assert frame_count == 36
    assert metrics["maximum_quaternion_norm_error"] == 0.0
    with pytest.raises(ValueError, match="outside deployment mask"):
        validate_planner_outputs(qpos, np.asarray([24], dtype=np.int32))


def test_output_validation_rejects_nonfinite_valid_prefix():
    qpos, count = _valid_output()
    qpos[0, 10, 8] = np.nan
    with pytest.raises(ValueError, match="nonfinite"):
        validate_planner_outputs(qpos, count)


def test_resample_and_context_update_preserve_linear_motion():
    qpos, _ = _valid_output(36)
    source = qpos[0, :36].copy()
    source[:, 0] = np.arange(36, dtype=np.float32) / 30.0
    motion = resample_qpos_50hz(source)
    assert motion.shape == (60, 36)
    assert motion[10, 0] == pytest.approx(0.2)
    context = context_from_motion_50hz(motion, generation_frame=2)
    assert context.shape == (1, 4, 36)
    assert context[0, 0, 0] == pytest.approx(0.04)
    assert context[0, 1, 0] == pytest.approx(0.04 + 1.0 / 30.0)


def test_planner_inputs_fail_closed_on_zero_facing_direction():
    with pytest.raises(ValueError, match="nonzero"):
        build_planner_inputs(
            initialize_context(),
            mode=0,
            facing_direction=(0.0, 0.0, 0.0),
        )
