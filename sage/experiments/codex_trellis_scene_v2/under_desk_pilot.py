from __future__ import annotations

import argparse
import json
import math
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .capabilities import (
    capability_index,
    load_capability_registry,
    require_free_space,
    validate_capability_registry,
)
from .collision_proxy import VoxelSDF, build_capability_proxy, load_normalized_asset_mesh
from .io_utils import read_json, write_json
from .scene_graph import build_typed_scene_graph


PILOT_SCHEMA = "codex_trellis_under_desk_reference_guided_search_v2"
DEFAULT_PLACEMENTS = (
    {"id": "outside", "translation_m": [0.0, -0.75, 0.0], "yaw_degrees": 180.0},
    {"id": "tucked", "translation_m": [0.0, -0.55, 0.0], "yaw_degrees": 180.0},
    {
        "id": "overinserted",
        "translation_m": [0.0, -0.40, 0.0],
        "yaw_degrees": 180.0,
    },
)
DEFAULT_REFERENCE_TARGET = {
    "source": "synthetic_image_observation_contract",
    "translation_m": [0.04, -0.40, 0.0],
    "yaw_degrees": 170.0,
    "confidence": 0.85,
}


def _yaw_points(points: np.ndarray, degrees: float) -> np.ndarray:
    angle = math.radians(float(degrees))
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.asarray(
        ((cosine, -sine, 0.0), (sine, cosine, 0.0), (0.0, 0.0, 1.0)),
        dtype=np.float64,
    )
    return np.asarray(points, dtype=np.float64) @ rotation.T


def _axis_overlap(
    first_center: float,
    first_extent: float,
    second_center: float,
    second_extent: float,
) -> float:
    first_min = float(first_center) - float(first_extent) / 2.0
    first_max = float(first_center) + float(first_extent) / 2.0
    second_min = float(second_center) - float(second_extent) / 2.0
    second_max = float(second_center) + float(second_extent) / 2.0
    return max(0.0, min(first_max, second_max) - max(first_min, second_min))


def _angle_distance_degrees(first: float, second: float) -> float:
    return abs((float(first) - float(second) + 180.0) % 360.0 - 180.0)


def _rotated_footprint_extents(
    child_dimensions: dict[str, float], yaw_degrees: float
) -> tuple[float, float]:
    angle = math.radians(float(yaw_degrees))
    cosine = abs(math.cos(angle))
    sine = abs(math.sin(angle))
    width = float(child_dimensions["width"])
    length = float(child_dimensions["length"])
    return (
        cosine * width + sine * length,
        sine * width + cosine * length,
    )


def footprint_overlap_fraction(
    parent_dimensions: dict[str, float],
    child_dimensions: dict[str, float],
    *,
    x: float,
    y: float,
) -> float:
    overlap_x = _axis_overlap(
        0.0,
        float(parent_dimensions["width"]),
        float(x),
        float(child_dimensions["width"]),
    )
    overlap_y = _axis_overlap(
        0.0,
        float(parent_dimensions["length"]),
        float(y),
        float(child_dimensions["length"]),
    )
    child_area = float(child_dimensions["width"]) * float(
        child_dimensions["length"]
    )
    return float(overlap_x * overlap_y / max(child_area, 1e-12))


def free_space_footprint_overlap_fraction(
    free_space: dict[str, Any],
    child_dimensions: dict[str, float],
    *,
    x: float,
    y: float,
    yaw_degrees: float,
) -> float:
    minimum = [float(value) for value in free_space["min_m"]]
    maximum = [float(value) for value in free_space["max_m"]]
    region_center_x = (minimum[0] + maximum[0]) / 2.0
    region_center_y = (minimum[1] + maximum[1]) / 2.0
    region_width = maximum[0] - minimum[0]
    region_length = maximum[1] - minimum[1]
    child_width, child_length = _rotated_footprint_extents(
        child_dimensions, yaw_degrees
    )
    overlap_x = _axis_overlap(
        region_center_x, region_width, float(x), child_width
    )
    overlap_y = _axis_overlap(
        region_center_y, region_length, float(y), child_length
    )
    child_area = child_width * child_length
    return float(overlap_x * overlap_y / max(child_area, 1e-12))


def classify_under_desk_points(
    desk_sdf: VoxelSDF,
    local_points: np.ndarray,
    *,
    parent_dimensions: dict[str, float],
    child_dimensions: dict[str, float],
    translation_m: list[float],
    yaw_degrees: float,
    free_space: dict[str, Any] | None = None,
    minimum_footprint_overlap: float = 0.15,
    penetration_tolerance_m: float | None = None,
) -> dict[str, Any]:
    translation = np.asarray(translation_m, dtype=np.float64)
    world_points = _yaw_points(local_points, yaw_degrees) + translation.reshape(1, 3)
    started = time.perf_counter()
    signed_distances = desk_sdf.query(world_points)
    query_seconds = time.perf_counter() - started
    tolerance = (
        float(desk_sdf.pitch)
        if penetration_tolerance_m is None
        else float(penetration_tolerance_m)
    )
    deep_penetration = signed_distances < -tolerance
    if free_space is None:
        overlap = footprint_overlap_fraction(
            parent_dimensions,
            child_dimensions,
            x=float(translation[0]),
            y=float(translation[1]),
        )
        required_overlap = float(minimum_footprint_overlap)
        free_space_id = None
        entry_z_ok = float(translation[2]) < float(parent_dimensions["height"])
    else:
        overlap = free_space_footprint_overlap_fraction(
            free_space,
            child_dimensions,
            x=float(translation[0]),
            y=float(translation[1]),
            yaw_degrees=float(yaw_degrees),
        )
        required_overlap = float(
            free_space.get(
                "minimum_footprint_overlap", minimum_footprint_overlap
            )
        )
        free_space_id = str(free_space["id"])
        z_bounds = free_space["entry_pose"]["translation_bounds_m"]["z"]
        entry_z_ok = (
            float(z_bounds[0]) - 1e-9
            <= float(translation[2])
            <= float(z_bounds[1]) + 1e-9
        )
    enters_parent_footprint = overlap >= required_overlap
    below_parent_top = float(translation[2]) < float(parent_dimensions["height"])
    if not enters_parent_footprint or not below_parent_top or not entry_z_ok:
        classification = "outside"
    elif bool(deep_penetration.any()):
        classification = "collision"
    else:
        classification = "valid_under"
    return {
        "classification": classification,
        "point_count": int(len(world_points)),
        "query_seconds": round(float(query_seconds), 6),
        "translation_m": [float(value) for value in translation],
        "yaw_degrees": float(yaw_degrees),
        "footprint_overlap_fraction": round(float(overlap), 6),
        "minimum_footprint_overlap": float(required_overlap),
        "free_space_id": free_space_id,
        "enters_parent_footprint": bool(enters_parent_footprint),
        "below_parent_top": bool(below_parent_top),
        "entry_z_ok": bool(entry_z_ok),
        "minimum_signed_distance_m": round(float(signed_distances.min()), 6),
        "negative_point_count": int(np.count_nonzero(signed_distances < 0.0)),
        "deep_penetration_point_count": int(np.count_nonzero(deep_penetration)),
        "deep_penetration_fraction": round(float(deep_penetration.mean()), 8),
        "penetration_tolerance_m": float(tolerance),
    }


def _bounded_values(
    minimum: float, maximum: float, step: float
) -> list[float]:
    count = int(math.floor((float(maximum) - float(minimum)) / step + 1e-9))
    values = [float(minimum) + index * step for index in range(count + 1)]
    if not values or values[-1] < float(maximum) - 1e-9:
        values.append(float(maximum))
    return [round(value, 8) for value in values]


def _candidate_values_near(
    center: float,
    minimum: float,
    maximum: float,
    radius: float,
    step: float,
) -> list[float]:
    low = max(float(minimum), float(center) - float(radius))
    high = min(float(maximum), float(center) + float(radius))
    values = _bounded_values(low, high, step)
    values.append(min(max(float(center), float(minimum)), float(maximum)))
    return sorted({round(value, 8) for value in values})


def _pose_loss(
    pose: dict[str, float],
    reference_target: dict[str, Any],
    baseline_pose: dict[str, Any],
    free_space: dict[str, Any],
    classification: dict[str, Any],
) -> dict[str, float]:
    bounds = free_space["entry_pose"]["translation_bounds_m"]
    scales = {
        axis: max(float(values[1]) - float(values[0]), 0.05)
        for axis, values in bounds.items()
    }
    reference_translation = [
        float(value) for value in reference_target["translation_m"]
    ]
    baseline_translation = [float(value) for value in baseline_pose["translation_m"]]
    translation = [pose["x"], pose["y"], pose["z"]]
    reference_position = sum(
        ((translation[index] - reference_translation[index]) / scales[axis]) ** 2
        for index, axis in enumerate(("x", "y", "z"))
    )
    baseline_position = sum(
        ((translation[index] - baseline_translation[index]) / scales[axis]) ** 2
        for index, axis in enumerate(("x", "y", "z"))
    )
    yaw_scale = max(
        float(free_space["entry_pose"]["yaw_tolerance_degrees"]), 1.0
    )
    reference_yaw = (
        _angle_distance_degrees(
            pose["yaw"], float(reference_target["yaw_degrees"])
        )
        / yaw_scale
    ) ** 2
    baseline_yaw = (
        _angle_distance_degrees(pose["yaw"], float(baseline_pose["yaw_degrees"]))
        / yaw_scale
    ) ** 2
    confidence = min(
        1.0, max(0.0, float(reference_target.get("confidence", 0.0)))
    )
    observation_loss = reference_position + 0.25 * reference_yaw
    pose_change_loss = baseline_position + 0.25 * baseline_yaw
    tolerance = max(float(classification["penetration_tolerance_m"]), 1e-9)
    clearance_risk = max(
        0.0, -float(classification["minimum_signed_distance_m"])
    ) / tolerance
    total = (
        confidence * observation_loss
        + (1.0 - confidence) * pose_change_loss
        + 0.05 * clearance_risk
    )
    return {
        "total": round(float(total), 8),
        "observation": round(float(observation_loss), 8),
        "pose_change": round(float(pose_change_loss), 8),
        "clearance_risk": round(float(clearance_risk), 8),
        "reference_confidence": float(confidence),
    }


def optimize_tucked_under_pose(
    desk_sdf: VoxelSDF,
    chair_points: np.ndarray,
    *,
    parent_dimensions: dict[str, float],
    child_dimensions: dict[str, float],
    free_space: dict[str, Any],
    reference_target: dict[str, Any],
    baseline_pose: dict[str, Any],
) -> dict[str, Any]:
    """Coarse-to-fine deterministic search with capability/SDF hard gates."""

    allowed = {
        str(category) for category in free_space.get("allowed_categories", [])
    }
    if "office_chair" not in allowed:
        raise ValueError("free-space capability does not allow office_chair")
    bounds = free_space["entry_pose"]["translation_bounds_m"]
    required_yaw = float(free_space["entry_pose"]["yaw_degrees"])
    yaw_tolerance = float(
        free_space["entry_pose"]["yaw_tolerance_degrees"]
    )
    stages = (
        {"translation_step": 0.05, "yaw_step": 5.0, "global": True},
        {"translation_step": 0.025, "yaw_step": 2.5, "global": False},
        {"translation_step": 0.0125, "yaw_step": 1.25, "global": False},
    )
    best: dict[str, Any] | None = None
    seen: set[tuple[float, float, float, float]] = set()
    stage_reports: list[dict[str, Any]] = []
    totals = {
        "evaluated": 0,
        "outside_free_space": 0,
        "collision": 0,
        "valid": 0,
    }
    for stage_index, stage in enumerate(stages):
        translation_step = float(stage["translation_step"])
        yaw_step = float(stage["yaw_step"])
        if bool(stage["global"]) or best is None:
            xs = _bounded_values(
                float(bounds["x"][0]), float(bounds["x"][1]), translation_step
            )
            ys = _bounded_values(
                float(bounds["y"][0]), float(bounds["y"][1]), translation_step
            )
            zs = _bounded_values(
                float(bounds["z"][0]), float(bounds["z"][1]), translation_step
            )
            yaws = _bounded_values(
                required_yaw - yaw_tolerance,
                required_yaw + yaw_tolerance,
                yaw_step,
            )
        else:
            xs = _candidate_values_near(
                float(best["pose"]["x"]),
                float(bounds["x"][0]),
                float(bounds["x"][1]),
                float(stages[stage_index - 1]["translation_step"]),
                translation_step,
            )
            ys = _candidate_values_near(
                float(best["pose"]["y"]),
                float(bounds["y"][0]),
                float(bounds["y"][1]),
                float(stages[stage_index - 1]["translation_step"]),
                translation_step,
            )
            zs = _candidate_values_near(
                float(best["pose"]["z"]),
                float(bounds["z"][0]),
                float(bounds["z"][1]),
                float(stages[stage_index - 1]["translation_step"]),
                translation_step,
            )
            yaws = _candidate_values_near(
                float(best["pose"]["yaw"]),
                required_yaw - yaw_tolerance,
                required_yaw + yaw_tolerance,
                float(stages[stage_index - 1]["yaw_step"]),
                yaw_step,
            )
        stage_counts = {
            "evaluated": 0,
            "outside_free_space": 0,
            "collision": 0,
            "valid": 0,
        }
        for x in xs:
            for y in ys:
                for z in zs:
                    for yaw in yaws:
                        key = (
                            round(x, 8),
                            round(y, 8),
                            round(z, 8),
                            round(yaw, 8),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        stage_counts["evaluated"] += 1
                        totals["evaluated"] += 1
                        classification = classify_under_desk_points(
                            desk_sdf,
                            chair_points,
                            parent_dimensions=parent_dimensions,
                            child_dimensions=child_dimensions,
                            translation_m=[x, y, z],
                            yaw_degrees=yaw,
                            free_space=free_space,
                        )
                        status = str(classification["classification"])
                        if status == "outside":
                            stage_counts["outside_free_space"] += 1
                            totals["outside_free_space"] += 1
                            continue
                        if status == "collision":
                            stage_counts["collision"] += 1
                            totals["collision"] += 1
                            continue
                        stage_counts["valid"] += 1
                        totals["valid"] += 1
                        pose = {"x": x, "y": y, "z": z, "yaw": yaw}
                        loss = _pose_loss(
                            pose,
                            reference_target,
                            baseline_pose,
                            free_space,
                            classification,
                        )
                        candidate = {
                            "pose": pose,
                            "loss": loss,
                            "classification": classification,
                        }
                        if best is None or (
                            float(loss["total"]),
                            abs(x),
                            abs(_angle_distance_degrees(yaw, required_yaw)),
                            y,
                        ) < (
                            float(best["loss"]["total"]),
                            abs(float(best["pose"]["x"])),
                            abs(
                                _angle_distance_degrees(
                                    float(best["pose"]["yaw"]), required_yaw
                                )
                            ),
                            float(best["pose"]["y"]),
                        ):
                            best = candidate
        stage_reports.append(
            {
                "stage": stage_index + 1,
                "translation_step_m": translation_step,
                "yaw_step_degrees": yaw_step,
                **stage_counts,
                "best_pose": deepcopy(best["pose"]) if best else None,
                "best_loss": deepcopy(best["loss"]) if best else None,
            }
        )
    if best is None:
        raise RuntimeError("no hard-valid tucked_under pose was found")
    return {
        "ok": True,
        "method": "deterministic_coarse_to_fine_sdf_search",
        "hard_gates": [
            "named_free_space_overlap",
            "desk_solid_sdf_penetration",
            "entry_pose_bounds",
            "chair_facing_tolerance",
            "fixed_physical_chair_scale",
        ],
        "reference_target": deepcopy(reference_target),
        "baseline_pose": deepcopy(baseline_pose),
        "selected": best,
        "search_totals": totals,
        "stages": stage_reports,
    }


def compare_dense_and_sparse(
    desk_sdf: VoxelSDF,
    chair_mesh: trimesh.Trimesh,
    *,
    parent_dimensions: dict[str, float],
    child_dimensions: dict[str, float],
    placements: tuple[dict[str, Any], ...] = DEFAULT_PLACEMENTS,
    sparse_point_count: int = 4096,
    seed: int = 20260724,
    free_space: dict[str, Any] | None = None,
) -> dict[str, Any]:
    dense_points = np.asarray(chair_mesh.vertices, dtype=np.float64)
    sparse_points, _ = trimesh.sample.sample_surface(
        chair_mesh,
        int(sparse_point_count),
        seed=int(seed),
    )
    sparse_points = np.asarray(sparse_points, dtype=np.float64)
    cases: list[dict[str, Any]] = []
    for placement in placements:
        arguments = {
            "parent_dimensions": parent_dimensions,
            "child_dimensions": child_dimensions,
            "translation_m": list(placement["translation_m"]),
            "yaw_degrees": float(placement["yaw_degrees"]),
            "free_space": free_space,
        }
        dense = classify_under_desk_points(desk_sdf, dense_points, **arguments)
        sparse = classify_under_desk_points(desk_sdf, sparse_points, **arguments)
        cases.append(
            {
                "id": str(placement["id"]),
                "dense_reference": dense,
                "sparse_runtime_proxy": sparse,
                "classification_matches": (
                    dense["classification"] == sparse["classification"]
                ),
            }
        )
    dense_query_seconds = sum(
        float(case["dense_reference"]["query_seconds"]) for case in cases
    )
    sparse_query_seconds = sum(
        float(case["sparse_runtime_proxy"]["query_seconds"]) for case in cases
    )
    classifications_match = all(
        bool(case["classification_matches"]) for case in cases
    )
    return {
        "ok": classifications_match,
        "dense_point_count": int(len(dense_points)),
        "sparse_point_count": int(len(sparse_points)),
        "point_reduction_factor": round(
            float(len(dense_points)) / max(float(len(sparse_points)), 1.0), 3
        ),
        "dense_query_seconds": round(dense_query_seconds, 6),
        "sparse_query_seconds": round(sparse_query_seconds, 6),
        "observed_query_speedup": (
            round(dense_query_seconds / sparse_query_seconds, 3)
            if sparse_query_seconds > 0.0
            else None
        ),
        "classification_agreement_count": sum(
            bool(case["classification_matches"]) for case in cases
        ),
        "classification_case_count": len(cases),
        "cases": cases,
    }


def run_under_desk_pilot(
    registry_path: Path,
    asset_root: Path,
    output_dir: Path,
    *,
    sparse_point_count: int = 4096,
    seed: int = 20260724,
    verify_hash: bool = True,
    reference_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = load_capability_registry(registry_path)
    capabilities = capability_index(registry)
    desk = capabilities["desk_warm_oak_001"]
    chair = capabilities["office_chair_black_mesh_001"]
    free_space = require_free_space(desk, "under_desk")
    proxy_dir = output_dir / "collision_proxies"
    desk_sdf, _, desk_proxy_report = build_capability_proxy(
        desk,
        asset_root,
        proxy_dir / "desk_warm_oak_001.voxel_sdf.npz",
        verify_hash=verify_hash,
    )
    chair_mesh, chair_normalization = load_normalized_asset_mesh(
        chair,
        asset_root,
        verify_hash=verify_hash,
    )
    comparison = compare_dense_and_sparse(
        desk_sdf,
        chair_mesh,
        parent_dimensions=desk["coordinate_frame"]["canonical_dimensions"],
        child_dimensions=chair["coordinate_frame"]["canonical_dimensions"],
        sparse_point_count=int(sparse_point_count),
        seed=int(seed),
        free_space=free_space,
    )
    sparse_points, _ = trimesh.sample.sample_surface(
        chair_mesh,
        int(sparse_point_count),
        seed=int(seed),
    )
    sparse_points = np.asarray(sparse_points, dtype=np.float64)
    dense_points = np.asarray(chair_mesh.vertices, dtype=np.float64)
    target = deepcopy(reference_target or DEFAULT_REFERENCE_TARGET)
    baseline_pose = {
        "translation_m": [0.0, -0.75, 0.0],
        "yaw_degrees": 180.0,
    }
    optimization = optimize_tucked_under_pose(
        desk_sdf,
        sparse_points,
        parent_dimensions=desk["coordinate_frame"]["canonical_dimensions"],
        child_dimensions=chair["coordinate_frame"]["canonical_dimensions"],
        free_space=free_space,
        reference_target=target,
        baseline_pose=baseline_pose,
    )
    selected_pose = optimization["selected"]["pose"]
    dense_selected = classify_under_desk_points(
        desk_sdf,
        dense_points,
        parent_dimensions=desk["coordinate_frame"]["canonical_dimensions"],
        child_dimensions=chair["coordinate_frame"]["canonical_dimensions"],
        translation_m=[
            float(selected_pose["x"]),
            float(selected_pose["y"]),
            float(selected_pose["z"]),
        ],
        yaw_degrees=float(selected_pose["yaw"]),
        free_space=free_space,
    )
    required_yaw = float(free_space["entry_pose"]["yaw_degrees"])
    yaw_tolerance = float(
        free_space["entry_pose"]["yaw_tolerance_degrees"]
    )
    facing_preserved = (
        _angle_distance_degrees(float(selected_pose["yaw"]), required_yaw)
        <= yaw_tolerance + 1e-9
    )
    pilot_brief = {
        "room_type": "study",
        "room": {"width": 4.0, "length": 4.0, "height": 2.8},
        "architecture": {},
        "objects": [
            {
                "id": str(desk["asset_id"]),
                "asset_id": str(desk["asset_id"]),
                "category": str(desk["category"]),
                "placement_type": "floor",
                "dimensions": deepcopy(
                    desk["coordinate_frame"]["canonical_dimensions"]
                ),
                "dimension_policy": deepcopy(desk["dimension_policy"]),
                "free_space_volumes": deepcopy(desk["free_space_volumes"]),
            },
            {
                "id": str(chair["asset_id"]),
                "asset_id": str(chair["asset_id"]),
                "category": str(chair["category"]),
                "placement_type": "floor",
                "dimensions": deepcopy(
                    chair["coordinate_frame"]["canonical_dimensions"]
                ),
                "dimension_policy": deepcopy(chair["dimension_policy"]),
            },
        ],
        "relations": [
            {
                "source": str(chair["asset_id"]),
                "type": "tucked_under",
                "target": str(desk["asset_id"]),
                "strength": "hard",
                "provenance": "pilot_relation_contract",
                "parameters": {
                    "free_space_id": str(free_space["id"]),
                    "reference_frame": "target_local",
                    "preserve_facing": True,
                },
            },
            {
                "source": str(chair["asset_id"]),
                "type": "faces",
                "target": str(desk["asset_id"]),
                "strength": "hard",
                "provenance": "pilot_relation_contract",
                "parameters": {
                    "target_yaw_degrees": required_yaw,
                    "tolerance_degrees": yaw_tolerance,
                },
            },
        ],
        "constraint_scopes": [],
        "instance_groups": [],
    }
    typed_graph = build_typed_scene_graph(pilot_brief)
    tucked_relation = next(
        edge
        for edge in typed_graph["relations"]
        if edge["type"] == "tucked_under"
    )
    expected = {
        "outside": "outside",
        "tucked": "valid_under",
        "overinserted": "collision",
    }
    expected_checks = {
        case["id"]: (
            case["dense_reference"]["classification"] == expected[case["id"]]
            and case["sparse_runtime_proxy"]["classification"] == expected[case["id"]]
        )
        for case in comparison["cases"]
    }
    success_checks = {
        "all_dense_sparse_classifications_match": bool(comparison["ok"]),
        "all_expected_classifications_match": all(expected_checks.values()),
        "sparse_proxy_is_smaller": (
            int(comparison["sparse_point_count"])
            < int(comparison["dense_point_count"])
        ),
        "free_space_capability_bound": (
            tucked_relation["parameters"]["free_space_id"]
            == free_space["id"]
        ),
        "typed_graph_valid": bool(typed_graph["validation"]["ok"]),
        "runtime_search_found_valid_pose": (
            optimization["selected"]["classification"]["classification"]
            == "valid_under"
        ),
        "dense_reference_accepts_selected_pose": (
            dense_selected["classification"] == "valid_under"
        ),
        "dense_sparse_selected_classification_matches": (
            dense_selected["classification"]
            == optimization["selected"]["classification"]["classification"]
        ),
        "chair_facing_preserved": bool(facing_preserved),
        "fixed_physical_scale_preserved": (
            chair["dimension_policy"]["mode"] == "fixed_physical"
        ),
    }
    report = {
        "schema": PILOT_SCHEMA,
        "ok": all(success_checks.values()),
        "registry": str(registry_path),
        "asset_root": str(asset_root),
        "output_dir": str(output_dir),
        "experiment": {
            "name": "chair_tucked_under_desk",
            "reference_mode": "all_render_mesh_vertices",
            "runtime_mode": "deterministic_surface_sample",
            "sparse_point_count": int(sparse_point_count),
            "seed": int(seed),
            "classification_contract": [
                "outside",
                "valid_under",
                "collision",
            ],
            "agreement_gate": "exact classification equality for every case",
            "reference_role": "soft_pose_target_only",
            "geometry_authority": "named_free_space_plus_real_asset_sdf",
        },
        "capability_validation": validate_capability_registry(registry),
        "desk_proxy": desk_proxy_report,
        "chair_normalization": chair_normalization,
        "comparison": comparison,
        "typed_scene_graph": typed_graph,
        "free_space_capability": deepcopy(free_space),
        "reference_guided_optimization": optimization,
        "selected_pose_dense_reference": dense_selected,
        "expected_checks": expected_checks,
        "success_checks": success_checks,
        "limitations": [
            "The dense reference checks render-mesh vertices, not exact triangle-triangle intersection.",
            "The reviewed under_desk free-space and its 0.15 overlap threshold are asset-specific.",
            "The default reference target is a synthetic observation contract unless --reference-target-json is supplied.",
            "The coarse-to-fine search is an isolated relation pilot and is not yet called by whole-room repair.",
            "Query timings are local observations, not a cross-machine benchmark.",
        ],
    }
    write_json(output_dir / "under_desk_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare an all-vertex offline reference with a sparse runtime surface "
            "proxy for one chair-under-desk classification pilot."
        )
    )
    parser.add_argument(
        "--capability-registry",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "capabilities"
            / "pilot_desk_chair_v1.json"
        ),
    )
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sparse-point-count", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument(
        "--reference-target-json",
        type=Path,
        help=(
            "Optional extracted image observation with translation_m, "
            "yaw_degrees, confidence, and source."
        ),
    )
    parser.add_argument(
        "--verify-hash",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    report_path = output_dir / "under_desk_report.json"
    if report_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"{report_path} already exists; use --overwrite to replace pilot outputs"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_under_desk_pilot(
        args.capability_registry.expanduser().resolve(),
        args.asset_root.expanduser().resolve(),
        output_dir,
        sparse_point_count=int(args.sparse_point_count),
        seed=int(args.seed),
        verify_hash=bool(args.verify_hash),
        reference_target=(
            read_json(args.reference_target_json.expanduser().resolve())
            if args.reference_target_json
            else None
        ),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
