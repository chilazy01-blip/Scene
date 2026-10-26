"""Freeze conditional bounded carrying scope before any carrying physics."""

import argparse
import time
from pathlib import Path
from .model import authorize
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def freeze(main_root, output):
    admission = authorize(main_root)
    if output.exists():
        raise FileExistsError(output)
    document = {
        "schema": "conditional-contact-carry-protocol/v1",
        "main_goal_admission": admission,
        "frozen_utc_timestamp": time.time(),
        "max_static_placements": 504,
        "max_dynamic_grasp_candidates": 3,
        "candidate_order": "geometric score then closure; one placement per closure; no retries",
        "standing": {
            "observer_ticks": 100,
            "qualification_ticks": 50,
            "active_ticks": 100,
        },
        "walking": {
            "observer_ticks": 100,
            "qualification_ticks": 50,
            "short_ticks": 100,
            "full_ticks": 300,
            "max_conditions": 1,
        },
        "selection": "first independently accepted standing grip only; stop grasp search on first standing success",
        "max_per_stage_wall_s": 120,
        "payload": {
            "mass_kg": 0.05,
            "cylinder_radius_m": 0.02,
            "cylinder_half_height_m": 0.04,
            "free_unattached": True,
            "preloaded_not_pickup": True,
        },
        "grip_gate": {
            "consecutive_physics_steps_before_active": 100,
            "min_active_opposing_contact_fraction": 0.9,
            "max_relative_position_slip_m": 0.03,
            "min_object_height_m": 0.25,
            "non_hand_support_allowed": False,
        },
        "body_safety": "unchanged raw SONIC, official limits/PD/effort and original physical guards; observer support only",
        "exit": "first accepted full walk, first walking rejection, or all 3 standing candidates rejected; bounded honest feasibility attempt, no unlimited tuning",
        "dependencies": {
            p.name: _file_binding(p)
            for p in sorted(Path(__file__).parent.glob("*.py"))
            if not p.name.startswith("test")
        },
        "not_claimed": [
            "pickup",
            "new policy training",
            "production",
            "held-out generalization",
            "full body mesh collision",
        ],
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output, document)
    return document


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--main-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    freeze(a.main_root, a.output)
