"""Zero-physics tests of stage semantics; not grasp success evidence."""

from types import SimpleNamespace
from pathlib import Path
import numpy as np
import pytest
from . import control
from .engine import validated_admission


def test_anchor_records_measured_state_once_without_object_write(monkeypatch):
    def metrics(_, model, data):
        return {
            "local_position_m": data.xpos[1].tolist(),
            "opposing_finger_contact": True,
            "non_hand_contact": False,
            "height_m": 0.7,
        }

    monkeypatch.setattr(control, "payload_metrics", metrics)
    model = SimpleNamespace(
        body=lambda name: SimpleNamespace(id=0 if name.startswith("right") else 1),
        opt=SimpleNamespace(timestep=0.005),
    )
    data = SimpleNamespace(
        xpos=np.array([[0.0, 0, 0], [0.09, 0.03, 0]]),
        xmat=np.array([np.eye(3).ravel(), np.eye(3).ravel()]),
        qpos=np.arange(57.0),
    )
    tracker = control.GripTracker(
        {
            "anchor_physics_step": 140,
            "qualification_max_relative_speed_m_s": 0.02,
            "max_acquisition_displacement_m": 0.08,
        },
        [0.13, 0.05, 0],
    )
    before = data.qpos.copy()
    p = tracker.observe(None, model, data, 140)
    assert not p["held"] and not p["guard_rejected"]
    anchor = tracker.anchor.copy()
    data.xpos[1, 0] += 0.00001
    for step in range(141, 241):
        p = tracker.observe(None, model, data, step)
    assert tracker.consecutive == 100 and p["held"]
    np.testing.assert_array_equal(tracker.anchor, anchor)
    np.testing.assert_array_equal(data.qpos, before)
    with pytest.raises(RuntimeError, match="never be moved"):
        tracker.observe(None, model, data, 140)


def rows():
    s = {
        "payload": {
            "held": True,
            "relative_position_error_m": 0.001,
            "relative_rotation_error_rad": 0.01,
            "non_hand_contact": False,
            "height_m": 0.7,
        },
        "support_enabled": False,
        "support_wrench": [0] * 6,
        "up_component": 1.0,
        "pelvis_height_m": 0.75,
        "full_qpos_before": [0.0, 0.0],
        "full_qpos_after": [0.0, 0.0],
        "root_velocity_after_m_s": [0.0, 0.0, 0.0],
        "body_velocity_after_rad_s": [0.0] * 29,
        "feet": {
            side: {"ground_contact_force_max_n": 10} for side in ("left", "right")
        },
    }
    return [
        {"sonic_candidate_consumed_by_physics": True, "substeps": [s] * 4}
        for _ in range(100)
    ]


def test_short_walking_checks_retention_without_demanding_final_stop(monkeypatch):
    monkeypatch.setattr(
        control,
        "accept",
        lambda *a: (_ for _ in ()).throw(AssertionError("full stop gate wrongly used")),
    )
    assert control.acceptance(rows(), 100, {"carry_mode": "walking"})["passed"]


def test_standing_needs_hold_and_opposing_contact_retention():
    r = rows()
    assert control.acceptance(r, 100, {"carry_mode": "standing"})["passed"]
    r[0]["substeps"][0]["payload"]["held"] = False
    assert not control.acceptance(r, 100, {"carry_mode": "standing"})["passed"]


def test_missing_independent_admission_never_reaches_actuation(tmp_path):
    with pytest.raises(FileNotFoundError):
        validated_admission(tmp_path / "REPORT.json")


def test_corrected_independent_audit_restores_execution_timebase():
    import ast

    tree = ast.parse(Path(__file__).with_name("audit_corrected.py").read_text())
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    assert any(
        isinstance(node.targets[0], ast.Attribute)
        and ast.unparse(node.targets[0]) == "model.opt.timestep"
        and ast.unparse(node.value) == "native.SIMULATION_DT_S"
        for node in assignments
    )


def test_every_new_engine_step_updates_only_separate_hand_pd_first():
    import ast

    tree = ast.parse(Path(__file__).with_name("engine.py").read_text())
    count = 0
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and ast.unparse(statement.value.func) == "mujoco.mj_step"
            ):
                assert ast.unparse(body[index - 1].value.func) == "apply_hand"
                count += 1
    assert count == 2
