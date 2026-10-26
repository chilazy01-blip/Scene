"""Ownership and future-only reference checks, not physical evidence."""

from types import SimpleNamespace
import numpy as np
from .control import ARM, SONIC, guard_sonic_candidate
from . import task


def test_unconsumed_arm_outside_range_is_never_mistaken_for_applied_command():
    candidate = np.zeros(29)
    candidate[ARM[0]] = 10
    guard = guard_sonic_candidate(
        candidate, np.zeros(29), -np.ones(29), np.ones(29), active=True
    )
    assert guard["in_range"] and guard["step_safe"]
    candidate[SONIC[0]] = 10
    assert not guard_sonic_candidate(
        candidate, np.zeros(29), -np.ones(29), np.ones(29), active=True
    )["in_range"]


def test_receding_reference_starts_from_real_posture_and_leaves_past_untouched(
    monkeypatch,
):
    t = object.__new__(task.Task)
    t.stage = "reach"
    t.reference_events = []
    t.q = np.zeros((120, 36), dtype=np.float32)
    t.v = np.zeros((120, 29))
    t.mujoco = object()
    t.world_path = {
        "frame": 0,
        "duration": 60,
        "origin": np.array([0.0, 0, 0]),
        "goal": np.array([1.0, 0, 0]),
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
            "angles_rad": np.ones(7).tolist(),
            "position_error_m": 0.0,
            "orientation_error_rad": 0.0,
        }

    monkeypatch.setattr(task, "solve", solve)
    t.synchronize_reference(10, d)
    np.testing.assert_array_equal(t.q[:10], 0)
    np.testing.assert_array_equal(d.qpos, 0.2)
    np.testing.assert_array_equal(seen[0], d.qpos)
    assert len(seen) == 11 and t.reference_events[-1]["kind"] == "world_reference_knots"
