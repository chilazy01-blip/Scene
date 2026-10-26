"""World servo ownership and history contracts; no physical-success claim."""

from types import SimpleNamespace
import numpy as np
from . import task
from .control import ARM, SONIC


def make():
    t = object.__new__(task.Task)
    t.q = np.zeros((200, 36), dtype=np.float32)
    t.stage = "reach"
    t.model = object()
    t.mujoco = object()
    t.world_path = {
        "frame": 10,
        "duration": 60,
        "origin": np.array([1.0, 2, 3]),
        "goal": np.array([2.0, 2, 3]),
        "initial_R": np.eye(3),
        "rotation": np.eye(3),
    }
    return t


def test_world_servo_updates_only_arm_without_mutating_reference_or_actual(monkeypatch):
    t = make()
    q = np.zeros(57)
    d = SimpleNamespace(qpos=q)
    seen = []
    angles = np.arange(7) * 0.123456789

    def solve(mujoco, model, actual, position, rotation, **kwargs):
        seen.append((actual.copy(), position.copy()))
        return dict(
            angles_rad=angles.tolist(), position_error_m=0.0, orientation_error_rad=0.0
        )

    monkeypatch.setattr(task, "solve", solve)
    target = t.arm_reference(40, d)
    np.testing.assert_array_equal(target[ARM], angles)
    np.testing.assert_array_equal(target[SONIC], 0)
    np.testing.assert_array_equal(t.q, 0)
    np.testing.assert_array_equal(q, 0)
    np.testing.assert_allclose(seen[0][1], [1.5, 2, 3])


def test_carry_does_not_freeze_held_object_in_world_space(monkeypatch):
    t = make()
    t.stage = "carry"
    monkeypatch.setattr(
        task,
        "solve",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    t.arm_reference(40, SimpleNamespace(qpos=np.zeros(57)))
    assert t.servo_record is None
