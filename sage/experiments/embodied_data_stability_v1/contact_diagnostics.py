"""Contact-pair taxonomy used by bounded Source-A quality repair runs.

The original S1/S3 counter kept only one global maximum.  That made a deep
finger/object overlap, a short foot/ground impact, and ordinary table support
look like one problem.  This module keeps the global metric for compatibility
and adds mutually exclusive, per-category evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


OBJECT_TOKENS = ("red_block", "red_cylinder")
HAND_TOKEN = "right_hand"
FOOT_TOKENS = ("ankle", "foot")
GROUND_TOKENS = ("floor", "ground", "world")


def _has(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def classify_contact_pair(
    body_a: str,
    body_b: str,
    geom_a: str = "",
    geom_b: str = "",
) -> str:
    """Return one stable, mutually exclusive category for a contact pair."""

    a = f"{body_a} {geom_a}".lower()
    b = f"{body_b} {geom_b}".lower()
    pair = (a, b)
    has_object = tuple(_has(value, OBJECT_TOKENS) for value in pair)
    has_hand = tuple(HAND_TOKEN in value for value in pair)
    if (has_object[0] and has_hand[1]) or (has_object[1] and has_hand[0]):
        return "hand_object"

    target = tuple("table_white" in value for value in pair)
    if (has_object[0] and target[1]) or (has_object[1] and target[0]):
        return "object_target_table"

    source_table = tuple(
        "table" in value and "table_white" not in value for value in pair
    )
    if (has_object[0] and source_table[1]) or (
        has_object[1] and source_table[0]
    ):
        return "object_source_table"

    has_foot = tuple(_has(value, FOOT_TOKENS) for value in pair)
    has_ground = tuple(_has(value, GROUND_TOKENS) for value in pair)
    if (has_foot[0] and has_ground[1]) or (has_foot[1] and has_ground[0]):
        return "foot_ground"

    if has_hand[0] or has_hand[1]:
        return "hand_environment"
    if has_object[0] or has_object[1]:
        return "object_environment"

    robot_a = body_a.startswith(("left_", "right_", "pelvis", "torso", "waist"))
    robot_b = body_b.startswith(("left_", "right_", "pelvis", "torso", "waist"))
    if robot_a and robot_b:
        return "robot_self"
    return "other"


@dataclass
class _Category:
    contact_samples: int = 0
    steps: set[int] = field(default_factory=set)
    max_penetration_m: float = 0.0
    max_contact_force_n: float = 0.0
    penetration_peak: dict[str, Any] | None = None
    force_peak: dict[str, Any] | None = None


class CategorizedContactAudit:
    """Accumulate compact evidence without changing simulator state."""

    def __init__(self) -> None:
        self._categories: dict[str, _Category] = {}

    def observe(
        self,
        *,
        step: int,
        sim_time_s: float,
        body_a: str,
        body_b: str,
        geom_a: str,
        geom_b: str,
        distance_m: float,
        force_n: float,
    ) -> None:
        category = classify_contact_pair(body_a, body_b, geom_a, geom_b)
        record = self._categories.setdefault(category, _Category())
        record.contact_samples += 1
        record.steps.add(int(step))
        penetration = max(0.0, -float(distance_m))
        event = {
            "physics_step": int(step),
            "sim_time_s": float(sim_time_s),
            "body_pair": [body_a, body_b],
            "geom_pair": [geom_a, geom_b],
            "distance_m": float(distance_m),
            "penetration_m": penetration,
            "force_n": float(force_n),
        }
        if penetration > record.max_penetration_m:
            record.max_penetration_m = penetration
            record.penetration_peak = event
        if force_n > record.max_contact_force_n:
            record.max_contact_force_n = float(force_n)
            record.force_peak = event

    def report(self) -> dict[str, Any]:
        return {
            name: {
                "contact_samples": record.contact_samples,
                "physics_steps_with_contact": len(record.steps),
                "max_penetration_m": record.max_penetration_m,
                "max_contact_force_n": record.max_contact_force_n,
                "penetration_peak": record.penetration_peak,
                "force_peak": record.force_peak,
            }
            for name, record in sorted(self._categories.items())
        }
