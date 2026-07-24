from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .capabilities import (
    capability_index,
    load_capability_registry,
    validate_capability_registry,
)
from .collision_proxy import VoxelSDF, build_capability_proxy, load_normalized_asset_mesh
from .io_utils import write_json


PILOT_SCHEMA = "codex_trellis_under_desk_sparse_consistency_pilot_v1"
DEFAULT_PLACEMENTS = (
    {"id": "outside", "translation_m": [0.0, -0.75, 0.0], "yaw_degrees": 180.0},
    {"id": "tucked", "translation_m": [0.0, -0.55, 0.0], "yaw_degrees": 180.0},
    {
        "id": "overinserted",
        "translation_m": [0.0, -0.40, 0.0],
        "yaw_degrees": 180.0,
    },
)


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


def classify_under_desk_points(
    desk_sdf: VoxelSDF,
    local_points: np.ndarray,
    *,
    parent_dimensions: dict[str, float],
    child_dimensions: dict[str, float],
    translation_m: list[float],
    yaw_degrees: float,
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
    overlap = footprint_overlap_fraction(
        parent_dimensions,
        child_dimensions,
        x=float(translation[0]),
        y=float(translation[1]),
    )
    enters_parent_footprint = overlap >= float(minimum_footprint_overlap)
    below_parent_top = float(translation[2]) < float(parent_dimensions["height"])
    if not enters_parent_footprint or not below_parent_top:
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
        "minimum_footprint_overlap": float(minimum_footprint_overlap),
        "enters_parent_footprint": bool(enters_parent_footprint),
        "below_parent_top": bool(below_parent_top),
        "minimum_signed_distance_m": round(float(signed_distances.min()), 6),
        "negative_point_count": int(np.count_nonzero(signed_distances < 0.0)),
        "deep_penetration_point_count": int(np.count_nonzero(deep_penetration)),
        "deep_penetration_fraction": round(float(deep_penetration.mean()), 8),
        "penetration_tolerance_m": float(tolerance),
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
) -> dict[str, Any]:
    registry = load_capability_registry(registry_path)
    capabilities = capability_index(registry)
    desk = capabilities["desk_warm_oak_001"]
    chair = capabilities["office_chair_black_mesh_001"]
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
        },
        "capability_validation": validate_capability_registry(registry),
        "desk_proxy": desk_proxy_report,
        "chair_normalization": chair_normalization,
        "comparison": comparison,
        "expected_checks": expected_checks,
        "success_checks": success_checks,
        "limitations": [
            "The dense reference checks render-mesh vertices, not exact triangle-triangle intersection.",
            "The 0.15 footprint-overlap threshold is a pilot value and is not yet calibrated across asset families.",
            "The under relation is not yet part of the main typed scene-graph vocabulary.",
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
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
