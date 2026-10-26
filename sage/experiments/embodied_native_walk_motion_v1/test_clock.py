"""Reference/phase contract tests; synthetic fixtures are not robot evidence."""

from types import SimpleNamespace
import numpy as np
from .reference import Clock
from sage.experiments.embodied_native_walk_v1.test_acceptance_v1 import _synthetic, CASE


def make():
    q = np.zeros((600, 36))
    q[:, 3] = 1
    q[:, 0] = np.arange(600) * 0.007
    v = np.zeros((600, 29))
    d = SimpleNamespace(
        qpos=np.array([0.85, 2.8, 0.7569, 1.0, 0, 0, 0]), qvel=np.zeros(6), time=10.0
    )
    return Clock(q, v, CASE), d


def test_gait_never_starts_before_continuous_ten_seconds():
    c, d = make()
    c.update(499, d, _synthetic()[:1996])
    assert c.phase == "initial_stand"
    c.update(500, d, _synthetic()[:2000])
    assert c.phase == "walking" and c.walk_start == 500


def test_no_walking_on_unstable_standing_timeout():
    c, d = make()
    rows = list(_synthetic()[:2000])
    rows[-1] = dict(rows[-1], root_velocity_m_s=[0.041, 0, 0])
    c.update(750, d, rows)
    assert c.failure == "initial_stand_timeout" and c.walk_start is None


def test_brake_uses_actual_goal_progress_and_waits_for_physical_stop():
    c, d = make()
    c.update(500, d, _synthetic()[:2000])
    d.qpos[0] = 1.90
    d.qvel[0] = 0.2
    c.update(650, d, [])
    assert c.phase == "braking" and c.brake_frame == 205
    d.qpos[0] = 2.0
    c.update(705, d, [])
    assert c.phase == "braking"
    d.qvel[0] = 0
    c.update(706, d, [])
    assert c.phase == "final_stand"


def test_final_hold_has_real_five_second_window_and_no_pose_write():
    c, d = make()
    c.phase = "final_stand"
    c.walk_start = 0
    c.walk_origin = np.array([0.85, 2.8])
    c.final_tick = 700
    before = d.qpos.copy()
    c.update(949, d, _synthetic()[-1000:])
    assert not c.done
    c.update(950, d, _synthetic()[-1000:])
    assert c.done
    np.testing.assert_array_equal(d.qpos, before)


def test_last_reference_frame_retains_complete_lookahead_and_can_finish_braking():
    c, d = make()
    c.phase = "braking"
    c.walk_start = 0
    c.walk_origin = np.array([0.85, 2.8])
    c.brake_frame = 553
    c.brake_tick = 500
    d.qpos[0] = 2.0
    frame = c.update(800, d, [])
    assert frame == 554 and frame + 45 < len(c.q) and c.phase == "final_stand"
