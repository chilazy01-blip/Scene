"""Contract tests, not physical qualification."""

from types import SimpleNamespace
import numpy as np
from . import task
from .control import ARM


def test_future_reference_does_not_modify_actual_state_or_past(monkeypatch):
    t = object.__new__(task.Task)
    t.stage = "reach"
    t.reference_events = []
    t.q = np.zeros((120, 36), dtype=np.float32)
    t.v = np.zeros((120, 29))
    t.mujoco = object()
    t.world_path = {
        "frame": 0,
        "duration": 60,
        "origin": np.zeros(3),
        "goal": np.ones(3),
        "initial_R": np.eye(3),
        "rotation": np.eye(3),
    }
    names = list(task.ARM_NAMES)
    t.model = SimpleNamespace(
        joint=lambda n: SimpleNamespace(qposadr=np.array([7 + ARM[names.index(n)]]))
    )
    d = SimpleNamespace(qpos=np.ones(57) * 0.2)
    seen = []

    def solve(mj, m, q, pos, R, **kw):
        seen.append(q.copy())
        return {
            "angles_rad": [1.0] * 7,
            "position_error_m": 0.0,
            "orientation_error_rad": 0.0,
        }

    monkeypatch.setattr(task, "solve", solve)
    t.synchronize_reference(10, d)
    np.testing.assert_array_equal(t.q[:10], 0)
    np.testing.assert_array_equal(d.qpos, 0.2)
    np.testing.assert_array_equal(seen[0], d.qpos)
    assert len(seen) == 11


def test_carry_servo_never_pins_hand_to_world():
    t = object.__new__(task.Task)
    t.stage = "carry"
    t.q = np.zeros((120, 36), dtype=np.float32)
    t.world_path = {"forbidden": "must never be read"}
    result = t.arm_reference(10, SimpleNamespace())
    np.testing.assert_array_equal(result, np.zeros(29))
    assert t.servo_record is None
