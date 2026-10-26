"""Frozen task acceptance in task coordinates, with a true destination gate."""

import numpy as np
from sage.experiments.embodied_data_stability_v1.sonic_braking_acceptance import (
    accept as base_accept,
)


def accept(records, budget, case):
    result = base_accept(records, budget)
    rows = [r for r in records if r["sonic_candidate_consumed_by_physics"]]
    if not rows:
        return result
    yaw = case["start_yaw_rad"]
    direction = np.array([np.cos(yaw), np.sin(yaw)])
    side = np.array([-np.sin(yaw), np.cos(yaw)])
    xy = np.array([r["actual_root_xyz_after_m"][:2] for r in rows])
    start = np.array(rows[0]["actual_root_xyz_before_m"][:2])
    forward = float((xy[-1] - start) @ direction)
    lateral = float(np.max(np.abs((xy - start) @ side)))
    error = float(np.linalg.norm(xy[-1] - case["goal_xy_m"]))
    result["metrics"].update(
        forward_m=forward, lateral_deviation_m=lateral, target_error_m=error
    )
    result["gates"].update(
        minimum_forward=forward >= 0.2,
        lateral_quality=lateral <= 0.15,
        target_reached=error <= 0.15,
    )
    result["gates"]["no_environment_collision"] = all(
        not s["scene_collision_violation"] for r in rows for s in r["substeps"]
    )
    result["thresholds"] = {**result["thresholds"], "target_radius_m": 0.15}
    result["passed"] = all(result["gates"].values())
    return result
