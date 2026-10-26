"""Synthetic unit fixtures only; never physical validation evidence."""

import copy

import pytest

from sage.experiments.embodied_data_stability_v1.sonic_walk_stop_metrics import (
    stop_acceptance,
)


def fixture():
    records = []
    for tick in range(100):
        samples = []
        for k in range(4):
            n = tick * 4 + k
            x = min(n / 200, 1) * 0.1
            swing = 50 <= n < 80
            feet = {
                side: {"ground_contact_force_max_n": 30.0, "sole_clearance_m": 0.0}
                for side in ("left", "right")
            }
            if swing:
                feet["right"] = {
                    "ground_contact_force_max_n": 0.0,
                    "sole_clearance_m": 0.02,
                }
            samples.append(
                {
                    "support_enabled": False,
                    "support_wrench": [0.0] * 6,
                    "full_qpos_before": [x, 0.0],
                    "full_qpos_after": [x, 0.0],
                    "root_velocity_after_m_s": [0.0, 0.0, 0.0],
                    "body_velocity_after_rad_s": [0.0] * 29,
                    "feet": feet,
                }
            )
        records.append(
            {
                "sonic_candidate_consumed_by_physics": True,
                "substeps": samples,
                "actual_root_xyz_before_m": [min(tick / 50, 1) * 0.1, 0.0, 0.8],
                "actual_root_xyz_after_m": [min((tick + 1) / 50, 1) * 0.1, 0.0, 0.8],
            }
        )
    return records


def test_step_then_stationary_hold_passes():
    result = stop_acceptance(fixture())
    assert result["passed"]
    assert result["metrics"]["completed_cycles"] == {"left": 0, "right": 1}


@pytest.mark.parametrize(
    "mutation",
    [
        "sliding",
        "speed",
        "drift",
        "moving_joints",
        "no_double_support",
        "external_support",
        "partial",
    ],
)
def test_stop_rejects_incomplete_or_false_success(mutation):
    rows = fixture()
    if mutation == "partial":
        rows = rows[:-1]
    else:
        for row in rows:
            for sample in row["substeps"]:
                if mutation == "sliding":
                    sample["feet"]["right"]["sole_clearance_m"] = 0.005
                elif mutation == "speed":
                    sample["root_velocity_after_m_s"][0] = 0.081
                elif mutation == "drift":
                    sample["full_qpos_after"][0] += 0.021
                elif mutation == "moving_joints":
                    sample["body_velocity_after_rad_s"] = [0.61] * 29
                elif mutation == "no_double_support":
                    sample["feet"]["left"]["ground_contact_force_max_n"] = 0.0
                elif mutation == "external_support":
                    sample["support_wrench"][2] = 0.001
    assert not stop_acceptance(rows)["passed"]


def test_hold_must_pass_throughout_window_not_just_final_pose():
    rows = fixture()
    rows[-25]["substeps"][0]["root_velocity_after_m_s"][0] = 0.2
    assert not stop_acceptance(rows)["passed"]


def test_empty_trace_not_accepted():
    assert not stop_acceptance([])["passed"]


def test_qualification_is_not_counted_as_hold():
    rows = fixture()
    prefix = copy.deepcopy(rows)
    for row in prefix:
        row["sonic_candidate_consumed_by_physics"] = False
        for sample in row["substeps"]:
            sample["support_enabled"] = True
    assert stop_acceptance(prefix + rows)["passed"]


@pytest.mark.parametrize(
    "module_name, stop_frame",
    [
        ("sonic_walk_stop_transition", 40),
        ("sonic_walk_early_stop_transition", 20),
        ("sonic_walk_mid_stop_transition", 30),
    ],
)
def test_fixed_official_schedule_and_future_coverage(
    monkeypatch, module_name, stop_frame
):
    import importlib
    import numpy as np

    transition = importlib.import_module(
        "sage.experiments.embodied_data_stability_v1." + module_name
    )
    calls = []

    def fake_run(session, inputs):
        calls.append(inputs)
        qpos = np.zeros((1, 64, 36), dtype=np.float32)
        qpos[:, :, 2] = 0.79
        qpos[:, :, 3] = 1
        qpos[:, :, 7:] = 0.01 if inputs["mode"].item() == 0 else 0.02
        return qpos, np.array([44], dtype=np.int64), 0.01

    monkeypatch.setattr(transition.native, "_run_once", fake_run)
    reference, metadata, velocity = transition.build_transition_reference(object())
    assert [c["mode"].item() for c in calls] == [0, 1, 0, 0, 0]
    assert metadata["stop_command_frame"] == stop_frame
    assert len(reference) >= 145 and velocity.shape == (len(reference), 29)
    np.testing.assert_allclose(reference[:3, 7:], 0.01)
    np.testing.assert_allclose(reference[10, 7:], 0.02)
    assert calls[1]["target_vel"].item() == float(np.float32(0.35))
    assert all(c["target_vel"].item() == -1 for c in calls[2:])


def test_walking_admission_does_not_authorize_reactive_stop(tmp_path):
    import json
    from sage.experiments.embodied_data_stability_v1.sonic_reactive_stop_shadow import (
        validated_admission,
    )
    from sage.experiments.embodied_data_stability_v1.audit_candidates import (
        canonical_sha256,
    )

    report = {"schema": "sonic-slow-walk-paced-shadow/v1", "classification": "passed"}
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    path = tmp_path / "walking.json"
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError, match="playing-reference configuration"):
        validated_admission(path)
