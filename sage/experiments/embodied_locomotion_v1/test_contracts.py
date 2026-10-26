"""Synthetic tests; these do not count toward the physical case matrix."""

import numpy as np
import pytest

from .reference import GoalClock
from .support import AnchoredBand
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    load_official_band,
)


def test_goal_trigger_uses_measured_distance_not_fixed_phase():
    q = np.zeros((600, 36))
    q[:, 3] = 1
    q[:, 2] = 0.79
    q[:, 0] = np.arange(600) * 0.006
    v = np.zeros((600, 29))
    events = []
    for distance in (0.4, 0.7):
        clock = GoalClock(
            {
                "start_yaw_rad": 0.0,
                "start_xy_m": [0.0, 0.0],
                "goal_distance_m": distance,
            }
        )
        for frame in range(120):
            clock.update(q, v, frame, [frame * 0.006, 0, 0.79], [0.3, 0, 0])
        events.append(clock.event)
        assert not np.any(clock.v[clock.stop :])
    assert events[0] < events[1]


def test_future_brake_pose_cannot_affect_pre_event_reference():
    q = np.zeros((600, 36))
    q[:, 3] = 1
    q[:, 2] = 0.79
    v = np.ones((600, 29))
    clock = GoalClock(
        {"start_yaw_rad": 0.0, "start_xy_m": [0.0, 0.0], "goal_distance_m": 0.7}
    )
    selected = clock.update(q, v, 110, [0.3, 0, 0.79], [0.3, 0, 0])
    assert selected[0] is q and selected[1] is v and clock.event is None


def test_translated_rotated_observer_anchor_preserves_official_law():
    yaw = 0.3
    c, s = np.cos(yaw), np.sin(yaw)
    rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    band = AnchoredBand([1.0, 2.0], yaw)
    band.band.length = -0.2
    pose = np.zeros(13)
    pose[:3] = [1.0, 2.0, 0.79]
    pose[3:7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
    wrench = band.Advance(pose)
    direct = load_official_band()
    direct.length = -0.2
    local = np.zeros(13)
    local[2] = 0.79
    local[3] = 1
    expected = direct.Advance(local)
    np.testing.assert_allclose(
        wrench, np.r_[rotation @ expected[:3], rotation @ expected[3:]], atol=1e-10
    )


def test_engine_rejects_missing_case_before_any_output(tmp_path):
    pytest.importorskip("mujoco")
    from .engine import run_shadow

    with pytest.raises(ValueError, match="immutable case"):
        run_shadow(tmp_path / "not_created")
    assert not (tmp_path / "not_created").exists()
