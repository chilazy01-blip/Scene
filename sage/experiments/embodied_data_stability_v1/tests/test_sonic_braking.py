"""Synthetic reference and budget tests, never a physical success claim."""

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1 import (
    sonic_phase_braking_reference as phase,
)
from sage.experiments.embodied_data_stability_v1.sonic_braking_reference import (
    select_reference,
)
from sage.experiments.embodied_data_stability_v1.sonic_braking_acceptance import accept


def fake_walk(planner):
    q = np.zeros((225, 36))
    q[:, 2] = 0.79
    q[:, 3] = 1
    q[:, 0] = np.arange(225) * 0.006
    q[:, 7:] = np.sin(np.arange(225)[:, None] * 0.1) * 0.1
    return (
        q,
        {"mode": 1, "target_speed_m_s": 0.35},
        phase.native._reference_velocities(q),
    )


def test_reference_is_causal_and_terminal_hold_has_zero_velocity(monkeypatch):
    monkeypatch.setattr(phase, "walking", fake_walk)
    versions, metadata = phase.build_braking_reference(object())
    old, oldvel = select_reference(versions, 74)
    new, newvel = select_reference(versions, 75)
    np.testing.assert_array_equal(old[:75], new[:75])
    np.testing.assert_array_equal(old[75], new[75])
    np.testing.assert_allclose(
        new[130:], np.repeat(new[130:131], len(new) - 130, axis=0)
    )
    assert not np.any(newvel[130:])
    assert metadata["braking_method"].startswith("engineered")
    new[:] = 100  # inaccessible future plan must not change the pre-event source
    assert np.max(np.abs(select_reference(versions, 74)[0])) < 10


def test_pose_velocity_consistency_and_no_hard_switch(monkeypatch):
    monkeypatch.setattr(phase, "walking", fake_walk)
    versions, _ = phase.build_braking_reference(object())
    q, v = select_reference(versions, 75)
    np.testing.assert_array_equal(v[75:-1], np.diff(q[:, 7:], axis=0)[75:] / 0.02)
    assert np.max(np.abs(q[76, 7:] - q[75, 7:])) < 0.02


def test_full_duration_requires_bound_short_smoke(tmp_path):
    pytest.importorskip("mujoco")
    from sage.experiments.embodied_data_stability_v1.sonic_phase_braking_shadow import (
        run_shadow,
    )

    output = tmp_path / "not_started"
    with pytest.raises(RuntimeError, match="separately bound 2-second smoke"):
        run_shadow(output, active_budget_ticks=250)
    assert not output.exists()


def test_unbudgeted_duration_rejected_before_any_physics(tmp_path):
    pytest.importorskip("mujoco")
    from sage.experiments.embodied_data_stability_v1.sonic_phase_braking_shadow import (
        run_shadow,
    )

    with pytest.raises(ValueError, match="hard budgets"):
        run_shadow(tmp_path / "not_started", active_budget_ticks=9999)


def test_empty_task_trace_is_not_success():
    assert not accept([], 250)["passed"]
