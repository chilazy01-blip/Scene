"""Fail-closed SONIC command admission with no actuator or simulator path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class GuardDecision:
    mode: str
    candidate_safe: bool
    transmit: bool
    source: str | None
    target_rad: tuple[float, ...] | None
    reason: str
    consecutive_shadow_passes: int
    handoff_ready: bool


class SonicRuntimeGuard:
    """Qualify a shadow, then admit or reject complete 29-joint commands."""

    def __init__(
        self,
        *,
        lower_rad: Iterable[float],
        upper_rad: Iterable[float],
        max_abs_delta_rad: float,
        qualification_ticks: int,
    ) -> None:
        import numpy as np

        self._lower = np.asarray(tuple(lower_rad), dtype=np.float64)
        self._upper = np.asarray(tuple(upper_rad), dtype=np.float64)
        if self._lower.shape != (29,) or self._upper.shape != (29,):
            raise ValueError("guard envelopes must contain 29 values")
        if not np.isfinite(self._lower).all() or not np.isfinite(self._upper).all():
            raise ValueError("guard envelopes must be finite")
        if not bool((self._lower < self._upper).all()):
            raise ValueError("each lower guard bound must be below its upper bound")
        if not np.isfinite(max_abs_delta_rad) or max_abs_delta_rad <= 0:
            raise ValueError("guard slew limit must be finite and positive")
        if qualification_ticks <= 0:
            raise ValueError("guard qualification ticks must be positive")
        self.max_abs_delta_rad = float(max_abs_delta_rad)
        self.qualification_ticks = int(qualification_ticks)
        self.mode = "shadow"
        self.consecutive_shadow_passes = 0

    def _vector(self, values: Any) -> Any | None:
        import numpy as np

        result = np.asarray(values, dtype=np.float64)
        if result.shape != (29,) or not np.isfinite(result).all():
            return None
        return result

    def _safe(self, candidate: Any, previous: Any) -> tuple[bool, str, Any | None]:
        import numpy as np

        value = self._vector(candidate)
        prior = self._vector(previous)
        if value is None:
            return False, "candidate_not_finite_29_vector", None
        if prior is None:
            return False, "previous_command_not_finite_29_vector", None
        if bool(((value < self._lower) | (value > self._upper)).any()):
            return False, "candidate_outside_frozen_envelope", value
        if float(np.max(np.abs(value - prior))) > self.max_abs_delta_rad:
            return False, "candidate_exceeds_frozen_50hz_slew", value
        return True, "candidate_passed", value

    @property
    def handoff_ready(self) -> bool:
        return (
            self.mode == "shadow"
            and self.consecutive_shadow_passes >= self.qualification_ticks
        )

    def observe_shadow(self, candidate: Any, previous_command: Any) -> GuardDecision:
        if self.mode != "shadow":
            raise RuntimeError("shadow qualification is only valid in shadow mode")
        safe, reason, _ = self._safe(candidate, previous_command)
        self.consecutive_shadow_passes = (
            self.consecutive_shadow_passes + 1 if safe else 0
        )
        return GuardDecision(
            mode=self.mode,
            candidate_safe=safe,
            transmit=False,
            source=None,
            target_rad=None,
            reason=reason,
            consecutive_shadow_passes=self.consecutive_shadow_passes,
            handoff_ready=self.handoff_ready,
        )

    def activate(self) -> None:
        if not self.handoff_ready:
            raise RuntimeError("SONIC handoff requested before shadow qualification")
        self.mode = "active"

    def evaluate_active(
        self,
        candidate: Any,
        previous_command: Any,
        *,
        source_a_fallback: Any | None = None,
    ) -> GuardDecision:
        if self.mode != "active":
            raise RuntimeError("active evaluation requires active mode")
        safe, reason, value = self._safe(candidate, previous_command)
        if safe:
            return GuardDecision(
                mode=self.mode,
                candidate_safe=True,
                transmit=True,
                source="sonic",
                target_rad=tuple(float(item) for item in value),
                reason=reason,
                consecutive_shadow_passes=self.consecutive_shadow_passes,
                handoff_ready=False,
            )

        fallback_safe = False
        fallback = None
        if source_a_fallback is not None:
            fallback_safe, _, fallback = self._safe(
                source_a_fallback, previous_command
            )
        if fallback_safe:
            self.mode = "fallback"
            return GuardDecision(
                mode=self.mode,
                candidate_safe=False,
                transmit=True,
                source="source_a",
                target_rad=tuple(float(item) for item in fallback),
                reason=f"{reason};latched_safe_source_a_fallback",
                consecutive_shadow_passes=self.consecutive_shadow_passes,
                handoff_ready=False,
            )

        self.mode = "stopped"
        return GuardDecision(
            mode=self.mode,
            candidate_safe=False,
            transmit=False,
            source=None,
            target_rad=None,
            reason=f"{reason};no_safe_fallback_stop",
            consecutive_shadow_passes=self.consecutive_shadow_passes,
            handoff_ready=False,
        )

