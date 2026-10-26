"""Synthetic zero-step guard and bookkeeping tests, never carrying evidence."""

import ast
from pathlib import Path
import numpy as np
import pytest
from .model import build
from .control import apply


def test_main_goal_gate_prevents_early_carry_model_creation(tmp_path):
    with pytest.raises(FileNotFoundError):
        build(tmp_path / "unaccepted", tmp_path / "not_created")
    assert not (tmp_path / "not_created").exists()


def test_finger_controller_uses_separate_native_effort_limited_pd():
    class Data:
        pass

    d = Data()
    d.qpos = np.array([0.0, 0.5])
    d.qvel = np.array([0.1, 0.0])
    d.ctrl = np.zeros(4)
    hand = {
        "qpos": np.array([0, 1]),
        "dofs": np.array([0, 1]),
        "actuators": np.array([2, 3]),
        "target": np.array([0.8, 0.0]),
        "kp": np.array([2.0, 1.5]),
        "kd": 0.1,
        "effort": np.array([1.0, 1.4]),
        "names": ["a", "b"],
    }
    result = apply(None, d, hand)
    np.testing.assert_array_equal(d.ctrl[:2], 0.0)
    np.testing.assert_allclose(d.ctrl[2:], [1.0, -0.75])
    assert result["torque_nm"] == d.ctrl[2:].tolist()


def test_every_physics_step_has_fresh_hand_pd():
    tree = ast.parse(Path(__file__).with_name("engine.py").read_text())
    found = 0
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body):
            if (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Attribute)
                and statement.value.func.attr == "mj_step"
            ):
                previous = body[index - 1]
                assert isinstance(previous, ast.Assign)
                assert (
                    isinstance(previous.value, ast.Call)
                    and previous.value.func.id == "apply_hand"
                )
                found += 1
    assert found == 2


def test_palm_only_support_is_not_a_finger_grasp():
    mujoco = pytest.importorskip("mujoco")
    from .grasp import payload_metrics

    model = mujoco.MjModel.from_xml_string(
        '<mujoco><worldbody><body name="right_wrist_yaw_link" pos="0 0 .5"><geom type="box" size=".1 .1 .01"/></body><body name="payload" pos="0 0 .56"><freejoint name="payload_free"/><geom name="payload_geom" type="sphere" size=".05" mass=".05"/></body></worldbody></mujoco>'
    )
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    metrics = payload_metrics(mujoco, model, data)
    assert not metrics["opposing_finger_contact"] and not metrics["held"]
