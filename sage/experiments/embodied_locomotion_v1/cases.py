"""Immutable case definitions; pilot cases are separate from matrix outcomes."""

import argparse
import math
from pathlib import Path
import numpy as np

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def make_case(root, scene_id, distance, pose_id, seed, output):
    scene = root / "scenes" / scene_id / "physics_v2" / "SCENE.json"
    metadata = read_bound_json(scene)
    start = [0.85, 2.8] if pose_id == 0 else [0.85, 3.15]
    yaw = 0.0 if pose_id == 0 else math.radians(-5)
    goal = (
        np.array(start) + distance * np.array([math.cos(yaw), math.sin(yaw)])
    ).tolist()
    # Conservative swept robot envelope, preflight from final generated OBBs.
    clearance = 100.0
    for t in np.linspace(0, 1, 101):
        xy = (1 - t) * np.array(start) + t * np.array(goal)
        clearance = min(
            clearance,
            xy[0],
            xy[1],
            metadata["room"]["width"] - xy[0],
            metadata["room"]["length"] - xy[1],
        )
        for obj in metadata["obstacles"]:
            c, s = np.cos(obj["yaw_rad"]), np.sin(obj["yaw_rad"])
            delta = np.array([[c, s], [-s, c]]) @ (xy - obj["center"][:2])
            distance_to_box = float(
                np.linalg.norm(
                    np.maximum(np.abs(delta) - np.array(obj["dimensions"][:2]) / 2, 0)
                )
            )
            clearance = min(clearance, distance_to_box)
    if clearance < 0.35:
        raise ValueError(f"corridor envelope rejected {scene_id}: {clearance}")
    case = {
        "schema": "generated-locomotion-case/v1",
        "scene_id": scene_id,
        "scene_manifest_path": str(scene),
        "model_path": metadata["model"]["path"],
        "scene_manifest": _file_binding(scene),
        "start_xy_m": start,
        "start_yaw_rad": yaw,
        "goal_distance_m": distance,
        "goal_xy_m": goal,
        "initialization_seed": seed,
        "joint_noise_std_rad": 0.0005,
        "corridor_min_clearance_m": clearance,
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "held_out_evaluation": False,
    }
    case["content_sha256_excluding_this_field"] = canonical_sha256(case)
    if output.exists():
        raise FileExistsError(output)
    write_json_atomic(output, case)
    return case


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--scene", default="S01")
    p.add_argument("--distance", type=float, default=0.4)
    p.add_argument("--pose", type=int, default=0)
    p.add_argument("--seed", type=int, default=101)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    print(make_case(a.root, a.scene, a.distance, a.pose, a.seed, a.output))
