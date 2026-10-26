"""Synthetic counterexamples only: these tests are never robot episode evidence."""

from copy import deepcopy
from functools import lru_cache
import numpy as np
import pytest
from .acceptance_v1 import evaluate
from .motion_gate import require_environment_confirmation, require_motion_protocol

CASE = {"start_xy_m": [0.85, 2.8], "start_yaw_deg": 0.0, "goal_xy_m": [2.0, 2.8]}


@lru_cache(maxsize=1)
def _synthetic():
    out = []
    point = [0.85, 2.8, 0.76]
    zeros = np.zeros((50, 6)).tolist()
    qzeros = np.zeros(49).tolist()
    for i in range(4000):
        before = point.copy()
        if i < 2000:
            phase = "initial_stand"
            velocity = [0.0, 0.0, 0.0]
        elif i < 2800:
            phase = "walking"
            velocity = [1.15 / 4, 0.0, 0.0]
        elif i < 3000:
            phase = "braking"
            velocity = [0.0, 0.0, 0.0]
        else:
            phase = "final_stand"
            velocity = [0.0, 0.0, 0.0]
        if phase == "walking":
            point = [0.85 + 1.15 * (i - 1999) / 800, 2.8, 0.76]
        feet = {
            s: {"ground_force_n": 180.0, "clearance_m": 0.0} for s in ("left", "right")
        }
        if phase == "walking":
            for side, a, b in (("left", 20, 40), ("right", 60, 75)):
                if a <= i % 80 < b:
                    feet[side] = {"ground_force_n": 0.0, "clearance_m": 0.025}
        out.append(
            {
                "time_before_s": i * 0.005,
                "time_after_s": (i + 1) * 0.005,
                "phase": phase,
                "root_before_m": before,
                "root_after_m": point.copy(),
                "root_velocity_m_s": velocity,
                "body_joint_velocity_rad_s": [0.0] * 29,
                "feet": feet,
                "up_component": 1.0,
                "penetration_m": 0.0001,
                "contact_force_n": 200.0,
                "xfrc_applied": zeros,
                "qfrc_applied": qzeros,
                "forbidden_contacts": 0,
            }
        )
    return out


@pytest.fixture
def rows():
    return deepcopy(_synthetic())


def test_synthetic_metrics_meet_requested_windows_but_not_physics_audit(rows):
    r = evaluate(rows, CASE)
    assert r["task_metrics_passed"] and r["not_a_physics_audit"]
    assert (
        r["initial_stand"]["duration_s"] == 10 and r["final_stand"]["duration_s"] == 5
    )
    assert r["forward_m"] >= 1 and all(n > 0 for n in r["foot_cycles"].values())


def test_short_initial_stand_not_rounded_up(rows):
    r = evaluate(rows[1:], CASE)
    assert (
        not r["task_metrics_passed"] and not r["gates"]["initial_continuous_10s_stand"]
    )


def test_short_final_stand_not_rounded_up(rows):
    r = evaluate(rows[:-1], CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["final_continuous_5s_stand"]


def test_missing_interior_sample_cannot_join_standing_time(rows):
    rows.pop(1000)
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["continuous_time"]


def test_relabelled_or_reordered_phases_fail(rows):
    rows[2500]["phase"] = "initial_stand"
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["phase_order"]


def test_sliding_without_foot_cycles_is_not_walking(rows):
    for r in rows:
        for foot in r["feet"].values():
            foot.update(ground_force_n=180.0, clearance_m=0.0)
    r = evaluate(rows, CASE)
    assert r["gates"]["actual_forward_at_least_1m"]
    assert (
        not r["task_metrics_passed"]
        and not r["gates"]["actual_landing_cycles_both_feet"]
    )


def test_task_target_or_reference_is_not_actual_displacement(rows):
    for r in rows:
        r["root_before_m"] = [0.85, 2.8, 0.76]
        r["root_after_m"] = [0.85, 2.8, 0.76]
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["actual_forward_at_least_1m"]


def test_hidden_external_support_fails_even_when_standing_is_stable(rows):
    rows[100]["xfrc_applied"] = np.zeros((50, 6)).tolist()
    rows[100]["xfrc_applied"][1][2] = 0.1
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["no_external_support"]


def test_furniture_touch_is_not_accepted_as_standing(rows):
    rows[3100]["forbidden_contacts"] = 1
    r = evaluate(rows, CASE)
    assert (
        not r["task_metrics_passed"]
        and not r["gates"]["no_environment_or_nonfoot_floor_contact"]
    )


def test_too_fast_final_root_not_stopped(rows):
    rows[-1]["root_velocity_m_s"] = [0.041, 0.0, 0.0]
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["final_continuous_5s_stand"]


def test_unreported_root_reset_rejected(rows):
    rows[2500]["root_before_m"] = [0.0, 0.0, 0.76]
    r = evaluate(rows, CASE)
    assert not r["task_metrics_passed"] and not r["gates"]["continuous_root_state"]


def test_nonfinite_input_or_missing_measurements_fail_closed(rows):
    rows[100]["root_after_m"][0] = float("nan")
    assert not evaluate(rows, CASE)["task_metrics_passed"]
    del rows[100]["qfrc_applied"]
    assert not evaluate(rows, CASE)["task_metrics_passed"]


def test_no_environment_approval_cannot_create_episode_output(tmp_path):
    with pytest.raises(PermissionError, match="zero motion steps authorized"):
        require_environment_confirmation(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_environment_approval_alone_not_a_motion_protocol(tmp_path, monkeypatch):
    from . import motion_gate

    monkeypatch.setattr(
        motion_gate,
        "require_environment_confirmation",
        lambda root: {"plan": {}, "approval": {}},
    )
    with pytest.raises(PermissionError, match="dynamic protocol has not been frozen"):
        require_motion_protocol(tmp_path)
    assert list(tmp_path.iterdir()) == []
