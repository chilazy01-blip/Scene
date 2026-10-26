"""Complexity-aware budgets and post-export audits for Scene V2 GLB delivery."""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from PIL import Image

from .content_chain import content_hash, file_binding
from .io_utils import read_json, write_json
from .mesh_verifier import verify_mesh_intersection
from .scene_render_acceptance import evaluate_scene_render_manifest


SCHEMA = "scene-v2-delivery-optimization/v1"
CATEGORY_BASE_BUDGET = {
    "book_row": 20_000,
    "book_stack": 20_000,
    "bookcase": 600_000,
    "office_chair": 52_000,
    "bed": 48_000,
    "dresser_plant": 60_000,
    "potted_plant": 38_000,
    "wardrobe": 100_000,
    "table_lamp": 18_000,
    "dresser": 22_000,
    # Nightstands occupy a large, rectilinear silhouette in room-scale views.
    # Aggressive collapse creates visible drawer/front-edge loss even when the
    # bounding box remains exact, so keep a higher category floor than generic
    # small tables.
    "nightstand": 40_000,
    "door": 15_000,
    "desk": 25_000,
    "clock": 15_000,
    "alarm_clock": 15_000,
    "slipper": 15_000,
    "window": 10_000,
    "mug": 8_000,
    # Thin framed art becomes unstable in near-edge/top silhouettes sooner than
    # its small face count suggests.
    "wall_art": 10_000,
    "area_rug": 1_000,
}


def _mesh_object_id(geometry_name: str, object_ids: list[str]) -> str | None:
    matches = [object_id for object_id in object_ids if geometry_name.startswith(f"{object_id}_")]
    return max(matches, key=len) if matches else None


def _normal_curvature_proxy(mesh: trimesh.Trimesh) -> float:
    normals = np.asarray(mesh.face_normals, dtype=np.float64)
    if not len(normals):
        return 0.0
    indices = np.linspace(0, len(normals) - 1, min(len(normals), 4096), dtype=np.int64)
    sampled = np.abs(normals[indices])
    # Axis-aligned boxes approach zero; rounded/organic surfaces approach one.
    return float(np.clip(np.mean(1.0 - np.max(sampled, axis=1)) / 0.42, 0.0, 1.0))


def _silhouette_complexity_proxy(mesh: trimesh.Trimesh) -> float:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    if len(vertices) < 4:
        return 0.0
    indices = np.linspace(0, len(vertices) - 1, min(len(vertices), 2048), dtype=np.int64)
    points = vertices[indices]
    extents = np.maximum(np.ptp(points, axis=0), 1e-9)
    normalized = (points - points.min(axis=0)) / extents
    # Occupied bins across three projections are a stable outline-detail proxy
    # without constructing expensive million-face convex hulls.
    scores = []
    for first, second in ((0, 1), (0, 2), (1, 2)):
        cells = np.floor(normalized[:, [first, second]] * 31.999).astype(np.int64)
        scores.append(len({(int(a), int(b)) for a, b in cells}) / 1024.0)
    return float(np.clip(max(scores) * 1.8, 0.0, 1.0))


def choose_target_faces(
    category: str,
    before_faces: int,
    *,
    curvature: float,
    silhouette: float,
) -> int:
    if before_faces < 1_000:
        return int(before_faces)
    base = CATEGORY_BASE_BUDGET.get(category, 28_000)
    complexity_factor = 0.82 + 0.23 * float(curvature) + 0.15 * float(silhouette)
    return min(int(before_faces), max(2_000, int(round(base * complexity_factor))))


def build_budget(
    source_glb: Path,
    plan_path: Path,
    *,
    scene_face_budget: int = 800_000,
    enable_experimental_instancing: bool = False,
) -> dict[str, Any]:
    plan = read_json(plan_path)
    scene = trimesh.load(source_glb, force="scene", process=False)
    if not isinstance(scene, trimesh.Scene) or not scene.geometry:
        raise ValueError("source GLB contains no scene geometry")
    objects = {str(item["id"]): item for item in plan.get("objects", []) if isinstance(item, dict) and item.get("id")}
    object_ids = sorted(objects, key=len, reverse=True)
    rows: list[dict[str, Any]] = []
    for geometry_name, mesh in sorted(scene.geometry.items()):
        object_id = _mesh_object_id(str(geometry_name), object_ids)
        category = str(objects.get(object_id, {}).get("category") or "architecture")
        if object_id is None and "entry_door" in str(geometry_name):
            category = "door"
        elif object_id is None and "window" in str(geometry_name):
            category = "window"
        before_faces = int(len(mesh.faces))
        curvature = _normal_curvature_proxy(mesh)
        silhouette = _silhouette_complexity_proxy(mesh)
        target = choose_target_faces(
            category,
            before_faces,
            curvature=curvature,
            silhouette=silhouette,
        )
        rows.append(
            {
                "geometry_name": str(geometry_name),
                "object_id": object_id,
                "category": category,
                "before_faces": before_faces,
                "curvature_proxy": round(curvature, 6),
                "silhouette_complexity_proxy": round(silhouette, 6),
                "target_faces": target,
            }
        )
    target_total = sum(item["target_faces"] for item in rows)
    if target_total > scene_face_budget:
        reducible = [item for item in rows if item["before_faces"] >= 1_000]
        fixed = sum(item["target_faces"] for item in rows if item["before_faces"] < 1_000)
        scale = max(0.1, (scene_face_budget - fixed) / max(1, target_total - fixed))
        for item in reducible:
            item["target_faces"] = max(2_000, int(math.floor(item["target_faces"] * scale)))
    duplicate_pairs = (
        [["lamp_left", "lamp_right"], ["nightstand_left", "nightstand_right"]]
        if enable_experimental_instancing
        else []
    )
    result = {
        "schema": SCHEMA,
        "source_glb": str(source_glb.resolve()),
        "source_binding": file_binding(source_glb),
        "plan": str(plan_path.resolve()),
        "plan_binding": file_binding(plan_path),
        "scene_face_budget": int(scene_face_budget),
        "texture_max_resolution": 1024,
        "budget_basis": "category_base_adjusted_by_normal_curvature_and_projected_silhouette_complexity",
        "unknown_category_policy": "bounded_generic_budget",
        "duplicate_instance_pairs": duplicate_pairs,
        "instancing_policy": (
            "experimental_mesh_linking_enabled"
            if enable_experimental_instancing
            else "disabled_after_material_and_instance_mask_regression"
        ),
        "meshes": rows,
        "target_face_sum_before_instancing": sum(item["target_faces"] for item in rows),
    }
    result["content_hash"] = content_hash(result)
    return result


def _world_mesh(scene: trimesh.Scene, object_id: str) -> trimesh.Trimesh:
    parts = []
    for node in scene.graph.nodes_geometry:
        if not str(node).startswith(f"{object_id}_geometry_"):
            continue
        matrix, geometry_name = scene.graph.get(node)
        mesh = scene.geometry[geometry_name].copy()
        mesh.apply_transform(matrix)
        parts.append(mesh)
    if not parts:
        raise ValueError(f"missing geometry for {object_id}")
    return trimesh.util.concatenate(parts)


def audit_relation_pairs(scene: trimesh.Scene, relation_audit: dict[str, Any]) -> dict[str, Any]:
    results = []
    for item in relation_audit.get("relations", []):
        source_id = str(item["source_object_id"])
        target_id = str(item["target_object_id"])
        source = _world_mesh(scene, source_id)
        target = _world_mesh(scene, target_id)
        triangle = verify_mesh_intersection(source, target, maximum_candidate_pairs=250_000)
        old_triangle = item.get("triangle_verification", {})
        ok = bool(triangle.get("complete") and not triangle.get("intersects"))
        results.append(
            {
                "source_object_id": source_id,
                "target_object_id": target_id,
                "relation_type": item.get("relation_type"),
                "old_certificate_hash": item.get("certificate", {}).get("certificate_hash"),
                "old_triangle_complete": old_triangle.get("complete"),
                "old_triangle_intersects": old_triangle.get("intersects"),
                "optimized_visual_triangle_verification": triangle,
                "ok": ok,
            }
        )
    return {
        "schema": "scene-v2-optimized-visual-relation-audit/v1",
        "ok": all(item["ok"] for item in results),
        "relation_count": len(results),
        "accepted_relation_count": sum(bool(item["ok"]) for item in results),
        "results": results,
    }


def audit_delivery(
    source_glb: Path,
    optimized_glb: Path,
    budget_path: Path,
    relation_audit_path: Path,
) -> dict[str, Any]:
    source = trimesh.load(source_glb, force="scene", process=False)
    optimized = trimesh.load(optimized_glb, force="scene", process=False)
    if not isinstance(source, trimesh.Scene) or not isinstance(optimized, trimesh.Scene):
        raise ValueError("source and optimized files must be GLB scenes")
    budget = read_json(budget_path)
    relation_source = read_json(relation_audit_path)
    plan = read_json(Path(str(budget["plan"])))
    source_faces = sum(len(mesh.faces) for mesh in source.geometry.values())
    optimized_faces = sum(len(mesh.faces) for mesh in optimized.geometry.values())
    object_ids = sorted(
        {
            str(item.get("object_id"))
            for item in budget.get("meshes", [])
            if item.get("object_id")
        }
    )
    bounds_results = []
    for object_id in object_ids:
        before = _world_mesh(source, object_id)
        after = _world_mesh(optimized, object_id)
        center_error = float(np.max(np.abs(before.bounding_box.centroid - after.bounding_box.centroid)))
        extent_error = float(np.max(np.abs(before.extents - after.extents)))
        center_tolerance = 0.003
        extent_tolerance = 0.006
        bounds_results.append(
            {
                "object_id": object_id,
                "center_error_m": round(center_error, 8),
                "extent_error_m": round(extent_error, 8),
                "center_tolerance_m": center_tolerance,
                "extent_tolerance_m": extent_tolerance,
                "ok": center_error <= center_tolerance and extent_error <= extent_tolerance,
            }
        )
    relation = audit_relation_pairs(optimized, relation_source)
    from .build_sdf_complex_bedroom import _whole_scene_regression_audit
    from .whole_scene_audit import attach_glb_audit, audit_glb_world_transforms

    plan_audit = _whole_scene_regression_audit(plan, relation_source)
    glb_audit = audit_glb_world_transforms(plan, optimized)
    whole_scene = attach_glb_audit(plan_audit, glb_audit)
    report = {
        "schema": "scene-v2-delivery-optimization-audit/v1",
        "source": {"path": str(source_glb.resolve()), **file_binding(source_glb), "faces": source_faces},
        "optimized": {"path": str(optimized_glb.resolve()), **file_binding(optimized_glb), "faces": optimized_faces},
        "limits": {"maximum_bytes": 100_000_000, "maximum_faces": 1_000_000},
        "size_ok": optimized_glb.stat().st_size < 100_000_000,
        "face_budget_ok": optimized_faces <= 1_000_000,
        "required_object_bounds": {
            "ok": all(item["ok"] for item in bounds_results),
            "results": bounds_results,
        },
        "optimized_visual_relations": relation,
        "p001_p003_whole_scene_regression": whole_scene,
        "collision_and_capability_policy": {
            "visual_mesh_only_optimized": True,
            "collision_proxies_modified": False,
            "capability_certificates_modified": False,
            "old_certificates_retained_as_upstream_evidence_only": True,
            "optimized_visual_mesh_reverified_for_surface_intersection": True,
        },
    }
    report["ok"] = bool(
        report["size_ok"]
        and report["face_budget_ok"]
        and report["required_object_bounds"]["ok"]
        and relation["ok"]
        and whole_scene["ok"]
    )
    report["content_hash"] = content_hash(report)
    return report


def _decode_mask(view: dict[str, Any], object_id: str) -> np.ndarray:
    object_row = view["objects"][object_id]
    with Image.open(object_row.get("object_index_path") or view["object_index_path"]) as image:
        pixels = np.asarray(image.convert("I"), dtype=np.float64)
    maximum = float(object_row.get("object_index_max_pixel_value") or view.get("object_index_max_pixel_value") or 255)
    normalized = pixels / max(1.0, maximum)
    if str(object_row.get("object_index_transfer") or view.get("object_index_transfer")) == "srgb_from_linear":
        normalized = np.where(
            normalized <= 0.04045,
            normalized / 12.92,
            np.power((normalized + 0.055) / 1.055, 2.4),
        )
    denominator = int(object_row.get("object_index_denominator") or view.get("object_index_denominator") or 1)
    decoded = np.rint(normalized * max(1, denominator)).astype(np.int32)
    return decoded == int(object_row["pass_index"])


def mask_iou(first: np.ndarray, second: np.ndarray) -> tuple[float, int, int]:
    union = int(np.count_nonzero(first | second))
    intersection = int(np.count_nonzero(first & second))
    return (intersection / union if union else 1.0), intersection, union


def audit_render_ab(source_manifest_path: Path, optimized_manifest_path: Path, plan_path: Path) -> dict[str, Any]:
    source = read_json(source_manifest_path)
    optimized = read_json(optimized_manifest_path)
    plan = read_json(plan_path)
    source_acceptance = evaluate_scene_render_manifest(source, plan)
    optimized_acceptance = evaluate_scene_render_manifest(optimized, plan)
    source_views = source["qa_passes"]["views"]
    optimized_views = optimized["qa_passes"]["views"]
    rows = []
    per_object: dict[str, list[tuple[float, int]]] = {}
    total_intersection = 0
    total_union = 0
    for view_name in sorted(set(source_views) & set(optimized_views)):
        first_view = source_views[view_name]
        second_view = optimized_views[view_name]
        for object_id in sorted(set(first_view["objects"]) & set(second_view["objects"])):
            first = _decode_mask(first_view, object_id)
            second = _decode_mask(second_view, object_id)
            iou, intersection, union = mask_iou(first, second)
            if union < 16:
                continue
            total_intersection += intersection
            total_union += union
            if union >= 2_000:
                view_threshold = 0.70
            elif union >= 500:
                view_threshold = 0.25
            else:
                view_threshold = 0.20
            per_object.setdefault(object_id, []).append((iou, union))
            rows.append(
                {
                    "view": view_name,
                    "object_id": object_id,
                    "intersection_pixels": intersection,
                    "union_pixels": union,
                    "silhouette_iou": round(iou, 6),
                    "threshold": view_threshold,
                    "ok": iou >= view_threshold,
                }
            )
    critical_ids = {
        "explicit_office_chair",
        "explicit_desk",
        "sdf_books_1",
        "sdf_books_2",
        "sdf_books_3",
        "sdf_open_bookcase",
    }
    object_rows = []
    for object_id, observations in sorted(per_object.items()):
        values = [item[0] for item in observations]
        maximum_union = max(item[1] for item in observations)
        if object_id in critical_ids:
            threshold = 0.84
            threshold_class = "relation_critical"
        elif maximum_union >= 2_000:
            threshold = 0.80
            threshold_class = "large_silhouette"
        else:
            threshold = 0.50
            threshold_class = "small_or_occluded_silhouette"
        object_rows.append(
            {
                "object_id": object_id,
                "best_silhouette_iou": round(max(values), 6),
                "minimum_silhouette_iou": round(min(values), 6),
                "maximum_union_pixels": maximum_union,
                "evaluated_view_count": len(values),
                "threshold": threshold,
                "threshold_class": threshold_class,
                "ok": max(values) >= threshold,
            }
        )
    weighted_iou = total_intersection / max(1, total_union)
    report = {
        "schema": "scene-v2-render-optimization-ab/v1",
        "source_render_acceptance": source_acceptance,
        "optimized_render_acceptance": optimized_acceptance,
        "thresholds": {
            "per_view_scale_aware": {"union_ge_2000": 0.70, "union_ge_500": 0.25, "union_lt_500": 0.20},
            "per_object_best": {"relation_critical": 0.84, "large_silhouette": 0.80, "small_or_occluded": 0.50},
            "global_weighted_silhouette_iou": 0.93,
        },
        "global_weighted_silhouette_iou": round(weighted_iou, 6),
        "objects": object_rows,
        "views": rows,
    }
    report["ok"] = bool(
        source_acceptance["accepted"]
        and optimized_acceptance["accepted"]
        and weighted_iou >= 0.93
        and all(item["ok"] for item in object_rows)
        and all(item["ok"] for item in rows)
    )
    report["content_hash"] = content_hash(report)
    return report


def finalize_delivery(output_dir: Path, source_delivery: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    source_delivery = source_delivery.resolve()
    copies = {
        "layout_plan_final.json": "layout_plan_final.json",
        "relation_geometry_audit.json": "relation_geometry_audit_source_certificate.json",
        "whole_scene_regression_audit.json": "whole_scene_regression_audit_source.json",
        "glb_world_transform_audit.json": "glb_world_transform_audit_source.json",
    }
    for source_name, output_name in copies.items():
        source = source_delivery / source_name
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, output_dir / output_name)
    optimization = read_json(output_dir / "optimization_audit.json")
    render_ab = read_json(output_dir / "render_ab_audit.json")
    blender = read_json(output_dir / "blender_optimization_report.json")
    source_metrics = optimization["source"]
    optimized_metrics = optimization["optimized"]
    artifact_names = [
        "scene_sdf_complex_bedroom.glb",
        "optimization_budget.json",
        "blender_optimization_report.json",
        "optimization_audit.json",
        "render_ab_audit.json",
        "render_optimized/render_manifest.json",
        "render_optimized/scene_corner.png",
        "render_optimized/scene_front.png",
        "relationship_closeups/closeup_manifest.json",
        "relationship_closeups/optimized_bookcase_books_closeup.png",
        "relationship_closeups/optimized_desk_chair_closeup.png",
        "relationship_closeups_source/closeup_manifest.json",
        "relationship_closeups_source/optimized_bookcase_books_closeup.png",
        "relationship_closeups_source/optimized_desk_chair_closeup.png",
        *copies.values(),
    ]
    report = {
        "schema": "scene-v2-p010-final-delivery/v1",
        "ok": bool(optimization["ok"] and render_ab["ok"] and blender["ok"]),
        "source_delivery": str(source_delivery),
        "output_dir": str(output_dir),
        "first_phase_targets": {
            "maximum_bytes": 100_000_000,
            "maximum_faces": 1_000_000,
            "actual_bytes": optimized_metrics["bytes"],
            "actual_faces": optimized_metrics["faces"],
            "byte_reduction_fraction": round(1.0 - optimized_metrics["bytes"] / source_metrics["bytes"], 6),
            "face_reduction_fraction": round(1.0 - optimized_metrics["faces"] / source_metrics["faces"], 6),
        },
        "non_regression": {
            "p001_p003_whole_scene_ok": optimization["p001_p003_whole_scene_regression"]["ok"],
            "optimized_visual_relation_count": optimization["optimized_visual_relations"]["relation_count"],
            "optimized_visual_relations_ok": optimization["optimized_visual_relations"]["ok"],
            "render_ab_ok": render_ab["ok"],
            "global_weighted_silhouette_iou": render_ab["global_weighted_silhouette_iou"],
            "source_render_accepted": render_ab["source_render_acceptance"]["accepted"],
            "optimized_render_accepted": render_ab["optimized_render_acceptance"]["accepted"],
        },
        "progressive_delivery_features": {
            "texture_resolution_cap": 1024,
            "mesh_instancing": "experimental_candidate_rejected_for_material_and_instance_mask_regression",
            "meshopt_or_draco": "deferred_not_required_for_first_phase_target",
            "ktx2": "deferred_not_required_for_first_phase_target",
            "lod": "budgeted_delivery_is_lod0; additional_lods_deferred",
        },
        "artifacts": {
            name: {"path": str((output_dir / name).resolve()), **file_binding(output_dir / name)}
            for name in artifact_names
        },
    }
    report["content_hash"] = content_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    budget = subparsers.add_parser("budget")
    budget.add_argument("--source-glb", type=Path, required=True)
    budget.add_argument("--plan", type=Path, required=True)
    budget.add_argument("--output", type=Path, required=True)
    budget.add_argument("--scene-face-budget", type=int, default=800_000)
    budget.add_argument("--enable-experimental-instancing", action="store_true")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--source-glb", type=Path, required=True)
    audit.add_argument("--optimized-glb", type=Path, required=True)
    audit.add_argument("--budget", type=Path, required=True)
    audit.add_argument("--relation-audit", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    render_ab = subparsers.add_parser("render-ab")
    render_ab.add_argument("--source-manifest", type=Path, required=True)
    render_ab.add_argument("--optimized-manifest", type=Path, required=True)
    render_ab.add_argument("--plan", type=Path, required=True)
    render_ab.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--output-dir", type=Path, required=True)
    finalize.add_argument("--source-delivery", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "budget":
        report = build_budget(
            args.source_glb,
            args.plan,
            scene_face_budget=args.scene_face_budget,
            enable_experimental_instancing=args.enable_experimental_instancing,
        )
    elif args.command == "audit":
        report = audit_delivery(args.source_glb, args.optimized_glb, args.budget, args.relation_audit)
    elif args.command == "render-ab":
        report = audit_render_ab(args.source_manifest, args.optimized_manifest, args.plan)
    else:
        report = finalize_delivery(args.output_dir, args.source_delivery)
    output = args.output if hasattr(args, "output") else args.output_dir / "final_delivery_audit.json"
    write_json(output, report)
    print(json.dumps({"ok": report.get("ok", True), "output": str(output)}, ensure_ascii=False))
    return 0 if report.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
