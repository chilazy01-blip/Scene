import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_runtime_guard import (
    SonicRuntimeGuard,
)


def make_guard(qualification_ticks=3):
    return SonicRuntimeGuard(
        lower_rad=[-1.0] * 29,
        upper_rad=[1.0] * 29,
        max_abs_delta_rad=0.5,
        qualification_ticks=qualification_ticks,
    )


def test_shadow_never_transmits_and_requires_consecutive_passes():
    guard = make_guard()
    previous = np.zeros(29)
    for expected in (1, 2, 3):
        decision = guard.observe_shadow(np.full(29, 0.1), previous)
        assert decision.transmit is False
        assert decision.consecutive_shadow_passes == expected
    assert decision.handoff_ready is True
    guard.observe_shadow(np.full(29, 2.0), previous)
    assert guard.consecutive_shadow_passes == 0
    assert guard.handoff_ready is False


def test_activate_rejects_unqualified_handoff():
    guard = make_guard()
    with pytest.raises(RuntimeError, match="before shadow qualification"):
        guard.activate()


def test_active_candidate_is_forwarded_without_modification():
    guard = make_guard(qualification_ticks=1)
    previous = np.zeros(29)
    candidate = np.linspace(-0.2, 0.2, 29)
    guard.observe_shadow(candidate, previous)
    guard.activate()
    decision = guard.evaluate_active(candidate, previous)
    assert decision.transmit is True
    assert decision.source == "sonic"
    assert np.array_equal(np.asarray(decision.target_rad), candidate)


def test_failure_latches_only_a_safe_source_a_fallback():
    guard = make_guard(qualification_ticks=1)
    previous = np.zeros(29)
    guard.observe_shadow(np.zeros(29), previous)
    guard.activate()
    decision = guard.evaluate_active(
        np.full(29, 2.0), previous, source_a_fallback=np.full(29, 0.25)
    )
    assert decision.candidate_safe is False
    assert decision.transmit is True
    assert decision.source == "source_a"
    assert decision.mode == "fallback"
    assert np.array_equal(np.asarray(decision.target_rad), np.full(29, 0.25))


def test_failure_without_safe_fallback_stops_without_command():
    guard = make_guard(qualification_ticks=1)
    previous = np.zeros(29)
    guard.observe_shadow(np.zeros(29), previous)
    guard.activate()
    decision = guard.evaluate_active(
        np.full(29, 2.0), previous, source_a_fallback=np.full(29, -2.0)
    )
    assert decision.transmit is False
    assert decision.target_rad is None
    assert decision.mode == "stopped"


def test_nonfinite_candidate_fails_closed():
    guard = make_guard(qualification_ticks=1)
    previous = np.zeros(29)
    guard.observe_shadow(np.zeros(29), previous)
    guard.activate()
    candidate = np.zeros(29)
    candidate[4] = np.nan
    decision = guard.evaluate_active(candidate, previous)
    assert decision.transmit is False
    assert decision.mode == "stopped"
    assert "not_finite" in decision.reason
