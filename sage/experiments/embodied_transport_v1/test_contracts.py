"""Pure stage/reference contract checks, never transport success evidence."""

from types import SimpleNamespace
import numpy as np
from . import task


def make(monkeypatch):
    q = np.zeros((600, 36))
    q[:, 3] = 1
    q[:, 0] = np.arange(600) * 0.005
    monkeypatch.setattr(
        task, "walking", lambda planner: (q.copy(), np.zeros((600, 29)), {})
    )
    case = {
        "start_xy_m": [0.85, 2.8],
        "source_root_goal_xy_m": [1.25, 2.8],
        "source_object_xyz_m": [1.45, 2.4, 0.69],
        "target_object_xyz_m": [1.85, 2.4, 0.69],
    }
    return task.Task(
        None, case, SimpleNamespace(body=lambda name: SimpleNamespace(id=0)), None
    )


def test_reference_arm_goal_never_rewrites_executed_past(monkeypatch):
    t = make(monkeypatch)
    before = t.q.copy()
    t.arm_goal(125, np.ones(7) * 0.3, 50)
    np.testing.assert_array_equal(t.q[:126], before[:126])
    np.testing.assert_allclose(t.q[175, t.arm + 7], 0.3)


def test_initial_hand_empty_and_close_release_continuous(monkeypatch):
    t = make(monkeypatch)
    assert t.hand_fraction(0) == 0
    t.stage = "close"
    assert t.hand_fraction(0) == 0 and t.hand_fraction(50) == 1
    assert t.hand_fraction(25) == 0.5
    t.stage = "release"
    assert t.hand_fraction(0) == 1 and t.hand_fraction(50) == 0


def test_done_requires_target_support_and_hand_free_measured_window(monkeypatch):
    t = make(monkeypatch)
    t.stage = "settle"
    data = SimpleNamespace(
        xpos=np.zeros((1, 3)), xmat=np.eye(3).reshape(1, 9), qvel=np.zeros(6)
    )
    p = {
        "local_position_m": [0, 0, 0],
        "normal_forces_n": {"target": 0.5},
        "hand_contact": True,
        "linear_velocity_m_s": [0, 0, 0],
        "world_position_m": [1.85, 2.4, 0.69],
    }
    for frame in range(25):
        t.update(frame, data, p)
    assert not t.done
    p["hand_contact"] = False
    for frame in range(25, 50):
        t.update(frame, data, p)
    assert t.done and t.events[-1]["to"] == "done"


def test_braking_does_not_move_simulator_state(monkeypatch):
    t = make(monkeypatch)
    before = t.q.copy()
    t.brake(100)
    np.testing.assert_array_equal(t.q[:101], before[:101])
    np.testing.assert_array_equal(t.v[155:], 0)


def test_r5_ready_hand_close_and_release(monkeypatch):
    from .task_r5 import Task

    t = make(monkeypatch)
    t.__class__ = Task
    t.case["ready_fraction"] = 0.45
    assert t.hand_fraction(0) == 0.45
    t.stage = "close"
    assert t.hand_fraction(0) == 0.45 and t.hand_fraction(50) == 1
    t.stage = "release"
    assert t.hand_fraction(50) == 0


def test_r5_lift_uses_actual_support_height(monkeypatch):
    from .task_r5 import Task

    t = make(monkeypatch)
    t.__class__ = Task
    t.stage = "lift"
    t.case["support_top_m"] = 0.8
    t.anchor = np.zeros(3)
    d = SimpleNamespace(xpos=np.zeros((1, 3)), xmat=np.eye(3).reshape(1, 9))
    p = dict(
        local_position_m=[0, 0, 0],
        bottom_z_m=0.81,
        source_supported=False,
        target_supported=False,
        opposing=True,
    )
    for frame in range(50, 100):
        t.update(frame, d, p)
    assert t.stage == "lift" and t.stable == 0


def test_r5_pose_feedback_bounded(monkeypatch):
    from .task_r5 import Task

    t = make(monkeypatch)
    t.__class__ = Task
    t.rotation_bias = np.zeros(3)
    from scipy.spatial.transform import Rotation

    for _ in range(20):
        t.feedback(
            np.ones(3),
            np.eye(3),
            np.zeros(3),
            Rotation.from_rotvec([1, 0, 0]).as_matrix(),
        )
    assert np.linalg.norm(t.rotation_bias) <= 0.3500000001
    np.testing.assert_array_less(np.abs(t.bias), 0.060000001)


def test_policy_probe_changes_only_future_right_arm_reference():
    from .policy_probe import perturb

    q = np.arange(100 * 36, dtype=np.float64).reshape(100, 36) / 1000
    before = q.copy()
    arm = np.array([15, 16, 17, 18, 19, 20, 21])
    changed = perturb(q, arm, 30, np.full(7, 0.1))
    np.testing.assert_array_equal(q, before)
    np.testing.assert_array_equal(changed[:31], before[:31])
    other = [i for i in range(36) if i not in arm + 7]
    np.testing.assert_array_equal(changed[:, other], before[:, other])
    np.testing.assert_allclose(changed[60:, arm + 7] - before[60:, arm + 7], 0.1)


def test_graph_parser_reads_fields_and_rejects_truncation():
    from .quantization_review import fields
    import pytest

    parsed = list(fields(bytes([8, 150, 1, 34, 5]) + b"Round"))
    assert parsed[0] == (1, 0, 150)
    assert parsed[1][0:2] == (4, 2) and bytes(parsed[1][2]) == b"Round"
    with pytest.raises(ValueError):
        list(fields(bytes([34, 5]) + b"R"))
