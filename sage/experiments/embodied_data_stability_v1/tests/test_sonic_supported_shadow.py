import json

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1 import sonic_supported_shadow as supported
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


def test_previous_raw_action_is_latest_logged_history_and_padding_stays_zero():
    raw = np.arange(5 * 29, dtype=np.float32).reshape(5, 29) + 1
    rows = supported.last_action_rows(raw, 3)
    assert np.count_nonzero(rows[0]) == 0
    np.testing.assert_array_equal(rows[1:], raw[:3])
    # A future/raw slot must never influence an observation.
    raw[3:] = -999
    np.testing.assert_array_equal(rows, supported.last_action_rows(raw, 3))
    assert np.count_nonzero(supported.last_action_rows(raw, 0)) == 0


def test_missing_history_gravity_matches_official_zero_quaternion_formula():
    positions = np.repeat(np.asarray(supported.DEFAULT_ANGLES)[None, :], 3, axis=0)
    inputs = native._mapping_inputs(positions, np.zeros((3, 29)),
                                   np.repeat([[1, 0, 0, 0]], 3, axis=0), np.zeros((3, 3)))
    blocks = supported.official_decoder_blocks(inputs, 2, np.zeros(64), np.zeros((3, 29)))
    gravity = blocks["his_gravity_dir_10frame_step1"].reshape(10, 3)
    np.testing.assert_array_equal(gravity[:7], np.repeat([[0, 0, 1]], 7, axis=0))
    np.testing.assert_array_equal(gravity[7:], np.repeat([[0, 0, -1]], 3, axis=0))


def test_official_band_matches_global_position_and_rotation_equations():
    band = supported.load_official_band()
    theta = 0.2
    pose = np.array([0.1, -0.1, 0.9, np.cos(theta / 2), 0, 0, np.sin(theta / 2),
                     0.02, 0.03, -0.04, 0.1, 0.2, 0.3])
    expected = np.r_[10000 * (np.array([0, 0, 1]) - pose[:3]) - 1000 * pose[7:10],
                     -1000 * np.array([0, 0, theta]) - 10 * pose[10:13]]
    np.testing.assert_allclose(band.Advance(pose), expected, atol=1e-10)


def test_range_and_slew_guard_reject_exact_joint_without_changing_candidate():
    candidate = np.zeros(29)
    candidate[7] = native.MAX_CANDIDATE_STEP_RAD + 1e-6
    original = candidate.copy()
    guard = supported.guard_candidate(candidate, np.zeros(29), -np.ones(29), np.ones(29))
    assert not guard["step_safe"]
    assert guard["max_step_joint"] == supported.SONIC_BODY_JOINT_ORDER[7]
    candidate[8] = 1.01
    guard = supported.guard_candidate(candidate, np.zeros(29), -np.ones(29), np.ones(29))
    assert not guard["in_range"]
    assert guard["out_of_range_joints"][0]["joint"] == supported.SONIC_BODY_JOINT_ORDER[8]
    assert candidate[7] == original[7]


def test_physical_guard_detects_undeclared_force_on_another_body():
    mujoco = pytest.importorskip("mujoco")
    xml, _ = native.stripped_official_model_xml(native.DEFAULT_MODEL)
    model = mujoco.MjModel.from_xml_string(xml.decode())
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    body = model.body("pelvis").id
    force = supported.apply_official_band(mujoco, model, data, supported.load_official_band(), body)
    assert supported.physical_guard(mujoco, model, data, body, force)["only_declared_support_wrench"]
    data.xfrc_applied[body + 1, 0] = 1
    assert not supported.physical_guard(mujoco, model, data, body, force)["only_declared_support_wrench"]


def test_admission_rejects_tampered_hash_before_any_physics(tmp_path):
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"classification": "passed", "content_sha256_excluding_this_field": "invalid"}))
    with pytest.raises(RuntimeError, match="hash mismatch"):
        supported.validated_admission(path)


def test_counterfactual_history_cannot_admit_real_command_history_runner(tmp_path):
    report = {
        "schema": "sonic-supported-shadow/v1", "classification": "passed",
        "sonic_only_physics_smoke_admission_ready": True,
        "sonic_candidate_actuator_writes": 0,
        "source_a_body_reference_used": False, "source_a_body_command_used": False,
        "longest_safe_candidate_run_ticks": 100,
        "history": "previous_counterfactual_sonic_raw_at_current_state_tick",
    }
    report["content_sha256_excluding_this_field"] = supported.canonical_sha256(report)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError, match="exact supported IDLE startup"):
        supported.validated_admission(path)


def test_grounded_support_is_exactly_two_official_key7_operations():
    band = supported.load_official_band()
    band.MujuocoKeyCallback(ord("7"))
    band.MujuocoKeyCallback(ord("7"))
    assert band.length == -0.2
    assert band.kp_pos == 10000 and band.kd_pos == 1000
    assert band.kp_ang == 1000 and band.kd_ang == 10
