import json

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1 import sonic_walk_shadow as walk
from sage.experiments.embodied_data_stability_v1 import (
    sonic_walk_transition as transition,
)


def _records(*, forward=0.1, lift=True):
    records = []
    for tick in range(100):
        if 20 <= tick < 35:
            left = {
                "sole_clearance_m": 0.02 if lift else 0.0,
                "ground_contact_force_max_n": 0.0,
            }
        else:
            left = {"sole_clearance_m": 0.0, "ground_contact_force_max_n": 50.0}
        if 50 <= tick < 65:
            right = {
                "sole_clearance_m": 0.02 if lift else 0.0,
                "ground_contact_force_max_n": 0.0,
            }
        else:
            right = {"sole_clearance_m": 0.0, "ground_contact_force_max_n": 50.0}
        records.append(
            {
                "sonic_candidate_consumed_by_physics": True,
                "candidate_safe": True,
                "actual_root_xyz_before_m": [forward * tick / 100, 0.0, 0.79],
                "actual_root_xyz_after_m": [forward * (tick + 1) / 100, 0.0, 0.79],
                "substeps": [
                    {
                        "feet": {"left": left, "right": right},
                        "support_enabled": False,
                        "support_wrench": [0.0] * 6,
                    }
                    for _ in range(4)
                ],
            }
        )
    return records


def test_walking_requires_both_foot_cycles_and_actual_forward_progress():
    result = walk.walking_acceptance(_records())
    assert result["passed"]
    assert result["completed_stance_swing_stance_cycles"] == {"left": 1, "right": 1}
    assert not walk.walking_acceptance(_records(forward=0.019))["passed"]
    assert not walk.walking_acceptance(_records(lift=False))["passed"]


def test_walking_rejects_external_support_or_incomplete_active_window():
    records = _records()
    records[50]["substeps"][0]["support_wrench"][2] = 1.0
    assert not walk.walking_acceptance(records)["passed"]
    assert not walk.walking_acceptance(_records()[:99])["passed"]


def test_transition_preserves_idle_prefix_and_fixed_low_speed(monkeypatch):
    calls = []

    def fake_run(session, inputs):
        calls.append(inputs)
        qpos = np.zeros((1, 64, 36), dtype=np.float32)
        qpos[:, :, 2] = 0.79
        qpos[:, :, 3] = 1.0
        qpos[:, :, 7:] = 0.01 if inputs["mode"].item() == 0 else 0.02
        return qpos, np.array([44], dtype=np.int64), 0.01

    monkeypatch.setattr(transition.native, "_run_once", fake_run)
    reference, metrics, velocity = transition.build_transition_reference(
        object(), speed=0.25, preserve_idle_seam=True
    )
    assert reference.shape == (225, 36)
    np.testing.assert_allclose(reference[:3, 7:], 0.01)
    np.testing.assert_allclose(reference[10, 7:], 0.02)
    assert metrics["target_speed_m_s"] == 0.25
    assert len(calls) == 5
    assert calls[0]["mode"].item() == 0
    assert all(call["target_vel"].item() == 0.25 for call in calls[1:])
    assert velocity.shape == (225, 29)


def test_idle_admission_cannot_authorize_walking(tmp_path):
    report = {"schema": "sonic-playing-shadow/v1", "classification": "passed"}
    report["content_sha256_excluding_this_field"] = walk.canonical_sha256(report)
    path = tmp_path / "idle.json"
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError):
        walk.validated_admission(path)


def test_official_scene_dynamics_and_fixed_hand_inertias_are_preserved():
    mujoco = pytest.importorskip("mujoco")
    from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
        official_body_model_xml,
    )

    payload, metadata = official_body_model_xml()
    model = mujoco.MjModel.from_xml_string(payload.decode())
    ids = walk.native._model_ids(mujoco, model)
    assert (model.nq, model.nv, model.nu) == (36, 35, 29)
    np.testing.assert_array_equal(model.dof_armature[ids["dof_ids"]], np.full(29, 0.01))
    np.testing.assert_array_equal(model.dof_damping[ids["dof_ids"]], np.full(29, 0.05))
    assert len(metadata["fixed_hand_joints"]) == 14
    assert model.body("left_hand_thumb_0_link").mass[0] > 0
    assert model.body("right_hand_thumb_0_link").mass[0] > 0
    import xml.etree.ElementTree as ET
    from sage.experiments.embodied_data_stability_v1.sonic_walk_official_model import (
        OFFICIAL_MODEL,
    )

    expected_mass = sum(
        float(x.attrib["mass"])
        for x in ET.parse(OFFICIAL_MODEL).getroot().findall(".//inertial")
    )
    assert model.body_mass.sum() == pytest.approx(expected_mass)
    assert model.ngeom == 9
