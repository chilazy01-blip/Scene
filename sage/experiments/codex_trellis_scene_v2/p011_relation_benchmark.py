from __future__ import annotations

import argparse
import hashlib
import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .build_sdf_complex_bedroom import (
    DEFAULT_ASSET_ROOT,
    DEFAULT_TRELLIS_ASSET_DIR,
    GEOMETRY_ASSET_IDS,
    _load_saved_runtime_asset,
)
from .exact_predicates import exact_predicate_capability
from .io_utils import read_json, write_json
from .mesh_verifier import (
    intersection_tolerance,
    prepare_triangle_mesh_cached,
    verify_mesh_intersection,
)
from .relation_geometry_bridge import evaluate_geometry_bindings
from .relation_geometry import (
    compile_relation_geometry,
    pose_matrix,
    transform_points,
)


P011_BENCHMARK_SCHEMA = "codex_trellis_p011_relation_benchmark_v1"


SURFACE_CASES = (
    (
        "chair_desk_clearance",
        "explicit_office_chair",
        "explicit_desk",
        False,
        "tucked_under",
    ),
    (
        "books_lower_container",
        "sdf_books_1",
        "sdf_open_bookcase",
        False,
        "contained_in",
    ),
    (
        "books_middle_container",
        "sdf_books_2",
        "sdf_open_bookcase",
        False,
        "contained_in",
    ),
    (
        "books_upper_container",
        "sdf_books_3",
        "sdf_open_bookcase",
        False,
        "contained_in",
    ),
    ("mug_desk_contact", "bedside_mug", "explicit_desk", False, "supported_by"),
    ("plant_dresser_contact", "dresser_plant", "dresser", False, "supported_by"),
    (
        "clock_nightstand_contact",
        "bedside_clock",
        "nightstand_left",
        False,
        "supported_by",
    ),
    ("lamp_left_contact", "lamp_left", "nightstand_left", False, "supported_by"),
    ("lamp_right_contact", "lamp_right", "nightstand_right", False, "supported_by"),
)

NEGATIVE_SURFACE_CASES = (
    (
        "chair_desk_penetration_negative",
        "explicit_office_chair",
        "explicit_desk",
        "raise_into_top",
    ),
    (
        "books_shelf_side_penetration_negative",
        "sdf_books_1",
        "sdf_open_bookcase",
        "move_into_right_side",
    ),
    ("mug_desk_penetration_negative", "bedside_mug", "explicit_desk", "lower_into_top"),
    (
        "plant_dresser_penetration_negative",
        "dresser_plant",
        "dresser",
        "lower_into_top",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def world_meshes(scene_path: Path) -> dict[str, trimesh.Trimesh]:
    scene = trimesh.load(scene_path, force="scene", process=False)
    result: dict[str, trimesh.Trimesh] = {}
    for node in scene.graph.nodes_geometry:
        object_id = str(node).removesuffix("_geometry_0")
        matrix, geometry_name = scene.graph[node]
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(matrix)
        result[object_id] = mesh
    return result


def run_surface_benchmark(scene_path: Path, cache_directory: Path) -> dict[str, Any]:
    meshes = world_meshes(scene_path)
    reports: list[dict[str, Any]] = []
    cases: list[tuple[str, trimesh.Trimesh, trimesh.Trimesh, bool, str]] = [
        (case_id, meshes[source_id], meshes[target_id], expected, relation_type)
        for case_id, source_id, target_id, expected, relation_type in SURFACE_CASES
    ]
    for case_id, source_id, target_id, perturbation in NEGATIVE_SURFACE_CASES:
        source, target = meshes[source_id].copy(), meshes[target_id]
        if perturbation == "raise_into_top":
            delta_x = float(np.mean(target.bounds[:, 0]) - np.mean(source.bounds[:, 0]))
            source.apply_translation((delta_x, 0.0, 0.0))
        elif perturbation == "lower_into_top":
            # glTF inspection coordinates are Y-up even though authoring is Z-up.
            delta_y = float(target.bounds[1, 1] - source.bounds[0, 1] - 0.01)
            source.apply_translation((0.0, delta_y, 0.0))
        elif perturbation == "move_into_right_side":
            delta_x = float(target.bounds[1, 0] - 0.02 - source.bounds[1, 0])
            source.apply_translation((delta_x, 0.0, 0.0))
        else:
            raise ValueError(perturbation)
        cases.append((case_id, source, target, True, "negative_penetration_fixture"))
    for pass_index in range(2):
        for case_id, source, target, expected, relation_type in cases:
            tolerance = intersection_tolerance(source, target)
            prepared = prepare_triangle_mesh_cached(
                target,
                transform=None,
                tolerance=tolerance,
                cache_directory=cache_directory,
            )
            started = time.perf_counter()
            verification = verify_mesh_intersection(
                source,
                target,
                prepared_second=prepared,
                maximum_candidate_pairs=500_000,
            )
            elapsed = time.perf_counter() - started
            reports.append(
                {
                    "pass": pass_index + 1,
                    "case_id": case_id,
                    "relation_type": relation_type,
                    "expected_surface_intersection": expected,
                    "observed_surface_intersection": verification["intersects"],
                    "matches_expected": bool(
                        verification["complete"]
                        and verification["intersects"] == expected
                    ),
                    "elapsed_seconds": elapsed,
                    "verification": verification,
                }
            )
    second_pass = [report for report in reports if report["pass"] == 2]
    return {
        "scene_glb": str(scene_path),
        "scene_glb_sha256": sha256(scene_path),
        "case_count": len(second_pass),
        "failure_count": sum(not report["matches_expected"] for report in second_pass),
        "failure_rate": (
            sum(not report["matches_expected"] for report in second_pass)
            / len(second_pass)
        ),
        "exact_verified_count": sum(
            report["verification"].get("verification_class")
            == "exact_predicate_verified"
            for report in second_pass
        ),
        "native_predicate_execution_case_count": sum(
            int(report["verification"].get("exact_predicate_tested_pair_count", 0)) > 0
            for report in second_pass
        ),
        "persistent_cache_hit_count": sum(
            report["verification"].get("static_target_bvh_persistent_hit", False)
            for report in second_pass
        ),
        "reports": reports,
    }


def run_relation_audits(
    geometry_run: Path,
    asset_root: Path,
    trellis_asset_directory: Path,
    cache_directory: Path,
) -> dict[str, Any]:
    plan = read_json(geometry_run / "layout_plan_final.json")
    binding = read_json(geometry_run / "relation_geometry_binding.json")
    runtime = {
        asset_id: _load_saved_runtime_asset(
            asset_id,
            asset_root=asset_root,
            trellis_asset_dir=trellis_asset_directory,
            output=geometry_run,
        )
        for asset_id in GEOMETRY_ASSET_IDS
    }
    legacy_audit = evaluate_geometry_bindings(
        plan,
        binding,
        runtime,
        static_target_bvh_cache_directory=cache_directory,
    )
    repaired_plan = deepcopy(plan)
    repaired_objects = {
        str(item["id"]): item for item in repaired_plan.get("objects", [])
    }
    repairs: list[dict[str, Any]] = []
    for item in binding["relations"]:
        if item["relation_type"] != "contained_in":
            continue
        source_object = repaired_objects[str(item["source_object_id"])]
        target_object = repaired_objects[str(item["target_object_id"])]
        source_asset = runtime[str(source_object["asset_id"])]
        target_asset = runtime[str(target_object["asset_id"])]
        contract = compile_relation_geometry(
            {
                "type": "contained_in",
                "target_slot_id": item["target_slot_id"],
            },
            source_asset.capability,
            target_asset.capability,
        )
        source_matrix = pose_matrix(
            {
                "x": source_object.get("x", 0.0),
                "y": source_object.get("y", 0.0),
                "z": source_object.get("z", 0.0),
                "yaw_degrees": source_object.get("yaw", 0.0),
            }
        )
        target_matrix = pose_matrix(
            {
                "x": target_object.get("x", 0.0),
                "y": target_object.get("y", 0.0),
                "z": target_object.get("z", 0.0),
                "yaw_degrees": target_object.get("yaw", 0.0),
            }
        )
        vertices_target = transform_points(
            transform_points(
                np.asarray(source_asset.mesh.vertices, dtype=np.float64), source_matrix
            ),
            np.linalg.inv(target_matrix),
        )
        slot = contract["target_slot"]
        clearance = float(slot.get("clearance_m", 0.0))
        minimum = np.asarray(slot["min_m"], dtype=np.float64) + clearance
        maximum = np.asarray(slot["max_m"], dtype=np.float64) - clearance
        current_minimum = np.min(vertices_target, axis=0)
        current_maximum = np.max(vertices_target, axis=0)
        delta_local = np.zeros(3, dtype=np.float64)
        guard = 1e-8
        for axis in range(3):
            if current_minimum[axis] < minimum[axis]:
                delta_local[axis] += minimum[axis] - current_minimum[axis] + guard
            if current_maximum[axis] + delta_local[axis] > maximum[axis]:
                delta_local[axis] -= (
                    current_maximum[axis] + delta_local[axis] - maximum[axis] + guard
                )
        if np.any(delta_local):
            delta_world = target_matrix[:3, :3] @ delta_local
            for axis, value in zip(("x", "y", "z"), delta_world):
                source_object[axis] = float(source_object.get(axis, 0.0) + value)
            repairs.append(
                {
                    "source_object_id": source_object["id"],
                    "target_object_id": target_object["id"],
                    "target_local_translation_m": delta_local.tolist(),
                    "world_translation_m": delta_world.tolist(),
                    "reason": "all-mesh-vertex convex containment correction",
                }
            )
    repaired_audit = evaluate_geometry_bindings(
        repaired_plan,
        binding,
        runtime,
        static_target_bvh_cache_directory=cache_directory,
    )
    return {
        "legacy_pose_audit": legacy_audit,
        "repaired_pose_audit": repaired_audit,
        "repairs": repairs,
        "repaired_plan": repaired_plan,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.output_directory.mkdir(parents=True, exist_ok=True)
    capability = exact_predicate_capability(
        cache_directory=args.output_directory / "native_backend"
    )
    relation_results = run_relation_audits(
        args.geometry_run,
        args.asset_root,
        args.trellis_asset_directory,
        args.output_directory / "relation_static_target_bvh",
    )
    relation_audit = relation_results["repaired_pose_audit"]
    surface = run_surface_benchmark(
        args.scene_glb, args.output_directory / "surface_static_target_bvh"
    )
    relations = relation_audit["relations"]
    ambiguous_samples = sum(
        int(report["certificate"]["collision"][direction].get("ambiguous_count") or 0)
        for report in relations
        for direction in ("source_to_target", "target_to_source")
    )
    sampled = sum(
        int(report["certificate"]["collision"][direction].get("sample_count") or 0)
        for report in relations
        for direction in ("source_to_target", "target_to_source")
    )
    refinement_count = sum(
        bool(
            report["certificate"]["collision"][direction]
            .get("local_refinement", {})
            .get("triggered")
        )
        for report in relations
        for direction in ("source_to_target", "target_to_source")
    )
    complete_containment = sum(
        report["certificate"]["predicate"].get("point_basis")
        == "all_mesh_vertices_convex_slot"
        and report["certificate"]["predicate"].get("classification_complete") is True
        for report in relations
    )
    result = {
        "schema": P011_BENCHMARK_SCHEMA,
        "ok": bool(
            capability.get("available")
            and relation_audit.get("ok")
            and surface["failure_count"] == 0
            and surface["native_predicate_execution_case_count"]
            >= len(NEGATIVE_SURFACE_CASES)
        ),
        "exact_predicate_capability": capability,
        "relation_audit": relation_audit,
        "legacy_pose_relation_audit": relation_results["legacy_pose_audit"],
        "containment_repairs": relation_results["repairs"],
        "repaired_layout_plan": relation_results["repaired_plan"],
        "surface_benchmark": surface,
        "statistics": {
            "relation_count": len(relations),
            "legacy_pose_relation_acceptance_failure_count": sum(
                not report["accepted"]
                for report in relation_results["legacy_pose_audit"]["relations"]
            ),
            "relation_acceptance_failure_count": sum(
                not report["accepted"] for report in relations
            ),
            "sdf_sample_count": sampled,
            "residual_sdf_ambiguous_count": ambiguous_samples,
            "residual_sdf_ambiguous_fraction": (
                ambiguous_samples / sampled if sampled else None
            ),
            "local_refinement_direction_count": refinement_count,
            "complete_convex_containment_count": complete_containment,
            "surface_case_count": surface["case_count"],
            "surface_failure_count": surface["failure_count"],
            "surface_failure_rate": surface["failure_rate"],
        },
        "default_repair_replacement": {
            "recommended": False,
            "reason": (
                "thirteen frozen real-scene cases are sufficient for an integration gate, "
                "not for replacing the default repair policy; expand nightly corpus first"
            ),
        },
    }
    output_path = args.output_directory / "p011_relation_benchmark.json"
    write_json(output_path, result)
    result["report_path"] = str(output_path)
    result["report_sha256"] = sha256(output_path)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--scene-glb", type=Path, required=True)
    result.add_argument("--geometry-run", type=Path, required=True)
    result.add_argument("--output-directory", type=Path, required=True)
    result.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    result.add_argument(
        "--trellis-asset-directory", type=Path, default=DEFAULT_TRELLIS_ASSET_DIR
    )
    return result


def main() -> int:
    result = run(parser().parse_args())
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "report_path": result["report_path"],
                "report_sha256": result["report_sha256"],
                "statistics": result["statistics"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
