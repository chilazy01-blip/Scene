from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .capabilities import (
    capability_index,
    load_capability_registry,
    validate_capability_registry,
)
from .collision_proxy import VoxelSDF, build_capability_proxy
from .io_utils import write_json


PILOT_SCHEMA = "codex_trellis_cup_on_desk_sdf_pilot_v1"


def _surface_sample(
    mesh: trimesh.Trimesh, count: int, seed: int
) -> np.ndarray:
    points, _ = trimesh.sample.sample_surface(mesh, int(count), seed=int(seed))
    return np.asarray(points, dtype=np.float64)


def _bottom_sample_mask(points: np.ndarray, height: float, pitch: float) -> np.ndarray:
    threshold = max(float(pitch) * 1.5, float(height) * 0.08)
    mask = points[:, 2] <= threshold
    if int(mask.sum()) < 64:
        cutoff = float(np.quantile(points[:, 2], 0.08))
        mask = points[:, 2] <= cutoff + 1e-9
    return mask


def _surface_footprint_ok(
    surface: dict[str, Any],
    *,
    x: float,
    y: float,
    object_width: float,
    object_length: float,
) -> bool:
    center = np.asarray(surface["center_m"], dtype=np.float64)
    u_axis = np.asarray(surface["u_axis"], dtype=np.float64)
    v_axis = np.asarray(surface["v_axis"], dtype=np.float64)
    offset = np.array([float(x), float(y), center[2]], dtype=np.float64) - center
    half_u, half_v = [float(item) for item in surface["half_extents_m"]]
    projected_u = abs(float(np.dot(offset, u_axis))) + float(object_width) / 2.0
    projected_v = abs(float(np.dot(offset, v_axis))) + float(object_length) / 2.0
    return projected_u <= half_u + 1e-9 and projected_v <= half_v + 1e-9


def _aabb_footprint_ok(
    parent_dimensions: dict[str, float],
    *,
    x: float,
    y: float,
    object_width: float,
    object_length: float,
) -> bool:
    return (
        abs(float(x)) + float(object_width) / 2.0
        <= float(parent_dimensions["width"]) / 2.0 + 1e-9
        and abs(float(y)) + float(object_length) / 2.0
        <= float(parent_dimensions["length"]) / 2.0 + 1e-9
    )


def evaluate_placement(
    desk_sdf: VoxelSDF,
    mug_surface_points: np.ndarray,
    mug_bottom_mask: np.ndarray,
    support_surface: dict[str, Any],
    *,
    bottom_z: float,
    x: float,
    y: float,
    mug_dimensions: dict[str, float],
    initial_bottom_z: float,
) -> dict[str, Any]:
    translation = np.array([float(x), float(y), float(bottom_z)], dtype=np.float64)
    world_points = mug_surface_points + translation.reshape(1, 3)
    signed_distances = desk_sdf.query(world_points)
    contact_tolerance = float(support_surface["contact_tolerance_m"])
    allowed_tolerance = np.zeros_like(signed_distances)
    allowed_tolerance[mug_bottom_mask] = contact_tolerance
    forbidden_penetration = np.maximum(
        0.0, -signed_distances - allowed_tolerance
    )
    bottom_distances = signed_distances[mug_bottom_mask]
    support_height = float(support_surface["center_m"][2])
    support_gap = float(bottom_z) - support_height
    return {
        "bottom_z": round(float(bottom_z), 6),
        "x": round(float(x), 6),
        "y": round(float(y), 6),
        "support_surface_id": str(support_surface["id"]),
        "signed_support_gap_m": round(support_gap, 6),
        "absolute_support_gap_m": round(abs(support_gap), 6),
        "bottom_sdf_mean_abs_m": round(
            float(np.mean(np.abs(bottom_distances))), 6
        ),
        "bottom_sdf_median_abs_m": round(
            float(np.median(np.abs(bottom_distances))), 6
        ),
        "maximum_forbidden_penetration_m": round(
            float(forbidden_penetration.max(initial=0.0)), 6
        ),
        "mean_forbidden_penetration_m": round(
            float(forbidden_penetration.mean()), 6
        ),
        "forbidden_collision_sample_fraction": round(
            float(np.mean(forbidden_penetration > 0.0)), 6
        ),
        "correct_support_surface_footprint": _surface_footprint_ok(
            support_surface,
            x=x,
            y=y,
            object_width=float(mug_dimensions["width"]),
            object_length=float(mug_dimensions["length"]),
        ),
        "translation_from_initial_m": round(
            abs(float(bottom_z) - float(initial_bottom_z)), 6
        ),
        "scale": [1.0, 1.0, 1.0],
        "dimension_policy_preserved": True,
    }


def _penetration_rms(metrics: dict[str, Any]) -> float:
    maximum = float(metrics["maximum_forbidden_penetration_m"])
    mean = float(metrics["mean_forbidden_penetration_m"])
    return float(np.sqrt(maximum * mean))


def compare_support_strategies(
    desk_sdf: VoxelSDF,
    mug_surface_points: np.ndarray,
    mug_bottom_mask: np.ndarray,
    support_surface: dict[str, Any],
    *,
    desk_aabb_top_z: float,
    mug_dimensions: dict[str, float],
    x: float,
    y: float,
) -> dict[str, Any]:
    initial_bottom_z = float(desk_aabb_top_z)
    surface_height = float(support_surface["center_m"][2])
    step = float(desk_sdf.pitch) / 2.0
    candidates = np.arange(
        max(0.0, min(initial_bottom_z, surface_height) - 0.12),
        max(initial_bottom_z, surface_height) + 0.081,
        step,
    )
    candidates = np.unique(
        np.concatenate(
            (
                candidates,
                np.asarray([initial_bottom_z, surface_height], dtype=np.float64),
            )
        )
    )

    evaluations = [
        evaluate_placement(
            desk_sdf,
            mug_surface_points,
            mug_bottom_mask,
            support_surface,
            bottom_z=float(candidate),
            x=float(x),
            y=float(y),
            mug_dimensions=mug_dimensions,
            initial_bottom_z=initial_bottom_z,
        )
        for candidate in candidates
    ]
    aabb = evaluate_placement(
        desk_sdf,
        mug_surface_points,
        mug_bottom_mask,
        support_surface,
        bottom_z=initial_bottom_z,
        x=float(x),
        y=float(y),
        mug_dimensions=mug_dimensions,
        initial_bottom_z=initial_bottom_z,
    )

    generic = deepcopy(
        min(
            evaluations,
            key=lambda metrics: (
                float(metrics["bottom_sdf_mean_abs_m"])
                + 20.0 * _penetration_rms(metrics)
                + 0.02 * float(metrics["translation_from_initial_m"]),
                float(metrics["translation_from_initial_m"]),
            ),
        )
    )
    capability = deepcopy(
        min(
            evaluations,
            key=lambda metrics: (
                5.0 * float(metrics["absolute_support_gap_m"])
                + 20.0 * _penetration_rms(metrics)
                + 0.005 * float(metrics["translation_from_initial_m"]),
                float(metrics["absolute_support_gap_m"]),
            ),
        )
    )

    aabb["method"] = "aabb_only"
    aabb["optimization_contract"] = "semantic_parent_aabb_top"
    generic["method"] = "generic_mesh_sdf"
    generic["optimization_contract"] = (
        "bottom_points_to_parent_sdf_without_named_support_surface"
    )
    capability["method"] = "capability_aware_sdf"
    capability["optimization_contract"] = (
        f"supported_by:{support_surface['id']}+forbid_parent_penetration"
    )
    return {
        "candidate_count": int(len(candidates)),
        "candidate_step_m": step,
        "placements": [aabb, generic, capability],
    }


def run_cup_on_desk_pilot(
    registry_path: Path,
    asset_root: Path,
    output_dir: Path,
    *,
    sample_count: int = 6000,
    seed: int = 20260724,
    verify_hash: bool = True,
) -> dict[str, Any]:
    registry = load_capability_registry(registry_path)
    capabilities = capability_index(registry)
    desk = capabilities["desk_warm_oak_001"]
    mug = capabilities["mug_white_001"]
    support_surface = deepcopy(desk["support_surfaces"][0])
    if mug["category"] not in support_surface["allowed_categories"]:
        raise ValueError("mug category is not allowed on selected support surface")

    proxy_dir = output_dir / "collision_proxies"
    desk_proxy, desk_mesh, desk_proxy_report = build_capability_proxy(
        desk,
        asset_root,
        proxy_dir / "desk_warm_oak_001.voxel_sdf.npz",
        verify_hash=verify_hash,
    )
    _, mug_mesh, mug_proxy_report = build_capability_proxy(
        mug,
        asset_root,
        proxy_dir / "mug_white_001.voxel_sdf.npz",
        verify_hash=verify_hash,
    )

    mug_points = _surface_sample(mug_mesh, sample_count, seed)
    mug_dimensions = mug["coordinate_frame"]["canonical_dimensions"]
    bottom_mask = _bottom_sample_mask(
        mug_points,
        float(mug_dimensions["height"]),
        float(desk_proxy.pitch),
    )
    surface_center = support_surface["center_m"]
    comparison = compare_support_strategies(
        desk_proxy,
        mug_points,
        bottom_mask,
        support_surface,
        desk_aabb_top_z=float(
            desk["coordinate_frame"]["canonical_dimensions"]["height"]
        ),
        mug_dimensions=mug_dimensions,
        x=float(surface_center[0]),
        y=float(surface_center[1]),
    )
    placement_by_method = {
        str(item["method"]): item for item in comparison["placements"]
    }
    aabb = placement_by_method["aabb_only"]
    capability = placement_by_method["capability_aware_sdf"]
    contact_tolerance = float(support_surface["contact_tolerance_m"])
    desk_dimensions = desk["coordinate_frame"]["canonical_dimensions"]
    edge_probe = {
        "x": float(desk_dimensions["width"]) / 2.0
        - float(mug_dimensions["width"]) / 2.0,
        "y": 0.0,
    }
    support_classification = {
        "probe": "mug_at_parent_aabb_edge",
        "x": round(edge_probe["x"], 6),
        "y": round(edge_probe["y"], 6),
        "aabb_parent_footprint_accepts": _aabb_footprint_ok(
            desk_dimensions,
            x=edge_probe["x"],
            y=edge_probe["y"],
            object_width=float(mug_dimensions["width"]),
            object_length=float(mug_dimensions["length"]),
        ),
        "capability_usable_surface_accepts": _surface_footprint_ok(
            support_surface,
            x=edge_probe["x"],
            y=edge_probe["y"],
            object_width=float(mug_dimensions["width"]),
            object_length=float(mug_dimensions["length"]),
        ),
        "interpretation": (
            "The parent AABB includes an edge placement that the reviewed usable "
            "support rectangle rejects."
        ),
    }
    success_checks = {
        "capability_surface_footprint_ok": bool(
            capability["correct_support_surface_footprint"]
        ),
        "capability_support_gap_within_tolerance": float(
            capability["absolute_support_gap_m"]
        )
        <= contact_tolerance + 1e-9,
        "capability_forbidden_penetration_within_voxel_tolerance": float(
            capability["maximum_forbidden_penetration_m"]
        )
        <= float(desk_proxy.pitch) + 1e-9,
        "capability_does_not_worsen_aabb_support_gap": float(
            capability["absolute_support_gap_m"]
        )
        <= float(aabb["absolute_support_gap_m"]) + 1e-9,
        "capability_rejects_aabb_edge_false_positive": bool(
            support_classification["aabb_parent_footprint_accepts"]
        )
        and not bool(
            support_classification["capability_usable_surface_accepts"]
        ),
        "dimension_policy_preserved": bool(
            capability["dimension_policy_preserved"]
        ),
    }
    report = {
        "schema": PILOT_SCHEMA,
        "ok": all(success_checks.values()),
        "registry": str(registry_path),
        "asset_root": str(asset_root),
        "output_dir": str(output_dir),
        "experiment": {
            "name": "cup_on_desk",
            "relation": {
                "source": "mug_white_001",
                "type": "supported_by",
                "target": "desk_warm_oak_001",
                "target_capability": "top",
                "strength": "hard",
            },
            "broad_phase": "canonical_dimensions_aabb",
            "narrow_phase": "voxel_sdf",
            "optimized_dofs": ["translation_z"],
            "locked_dofs": ["scale", "roll", "pitch", "yaw", "translation_x", "translation_y"],
            "surface_sample_count": int(sample_count),
            "bottom_sample_count": int(bottom_mask.sum()),
            "seed": int(seed),
        },
        "capability_validation": validate_capability_registry(registry),
        "collision_proxies": {
            "desk_warm_oak_001": desk_proxy_report,
            "mug_white_001": mug_proxy_report,
        },
        "comparison": comparison,
        "support_classification": support_classification,
        "observed_support_outcome": (
            "capability_improved_aabb_gap"
            if float(capability["absolute_support_gap_m"]) + 1e-9
            < float(aabb["absolute_support_gap_m"])
            else "capability_matched_aabb_gap"
        ),
        "success_checks": success_checks,
        "limitations": [
            "The voxel SDF is a cleaned proxy for non-watertight TRELLIS.2 geometry, not an exact manufacturing solid.",
            "The reviewed desk top capability is asset-specific and must not be copied to another desk.",
            "This pilot optimizes vertical translation only and does not yet modify the full V2 repair pipeline.",
            "No claim is made about dynamic friction, tipping, mass, or articulation.",
        ],
    }
    write_json(output_dir / "capability_validation.json", report["capability_validation"])
    write_json(output_dir / "cup_on_desk_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build minimal asset capabilities and compare AABB-only, generic mesh "
            "SDF, and capability-aware SDF support for one curated mug and desk."
        )
    )
    default_registry = (
        Path(__file__).resolve().parent
        / "capabilities"
        / "pilot_desk_mug_v1.json"
    )
    parser.add_argument(
        "--capability-registry",
        type=Path,
        default=default_registry,
    )
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-count", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=20260724)
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
    report_path = output_dir / "cup_on_desk_report.json"
    if report_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"{report_path} already exists; use --overwrite to replace pilot outputs"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    report = run_cup_on_desk_pilot(
        args.capability_registry.expanduser().resolve(),
        args.asset_root.expanduser().resolve(),
        output_dir,
        sample_count=int(args.sample_count),
        seed=int(args.seed),
        verify_hash=bool(args.verify_hash),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
