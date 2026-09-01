from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


VIEW_AXES = ("+x", "-x", "+y", "-y")


def generic_connected_platform_evidence(
    report: dict[str, Any],
    *,
    maximum_layered_footprint_ratio: float = 4.0,
    minimum_lower_full_width_fraction: float = 0.55,
    minimum_lower_overhang_ratio: float = 2.5,
    minimum_supporting_views: int = 2,
) -> dict[str, Any]:
    """Detect a broad platform even when TRELLIS fuses it into one mesh."""

    structure = report.get("structure_gate", {})
    footprint_ratio = float(
        structure.get("lower_to_upper_footprint_area_ratio", 0.0) or 0.0
    )
    supporting_views = []
    for axis, view in report.get("views", {}).items():
        full_width = float(view.get("lower_full_width_row_fraction", 0.0) or 0.0)
        overhang = float(view.get("lower_overhang_ratio", 0.0) or 0.0)
        if (
            full_width >= float(minimum_lower_full_width_fraction)
            and overhang >= float(minimum_lower_overhang_ratio)
        ):
            supporting_views.append(str(axis))
    triggered = bool(
        footprint_ratio > float(maximum_layered_footprint_ratio)
        and len(supporting_views) >= int(minimum_supporting_views)
    )
    return {
        "schema": "scene_detail_generic_connected_platform_evidence_v1",
        "evaluated": bool(report.get("evaluated")),
        "triggered": triggered,
        "lower_to_upper_footprint_area_ratio": round(footprint_ratio, 6),
        "maximum_layered_footprint_ratio": float(maximum_layered_footprint_ratio),
        "supporting_views": sorted(supporting_views),
        "minimum_supporting_views": int(minimum_supporting_views),
        "minimum_lower_full_width_fraction": float(minimum_lower_full_width_fraction),
        "minimum_lower_overhang_ratio": float(minimum_lower_overhang_ratio),
        "category_independent": True,
    }


def apply_generic_connected_platform_gate(
    report: dict[str, Any],
) -> dict[str, Any]:
    """Add the opt-in generic platform evidence to a multiview report copy."""

    updated = deepcopy(report)
    evidence = generic_connected_platform_evidence(updated)
    updated["generic_connected_platform_evidence"] = evidence
    structure = updated.get("structure_gate")
    if isinstance(structure, dict):
        existing_limit = structure.get("maximum_lower_to_upper_footprint_area_ratio")
        if existing_limit is None:
            structure["maximum_lower_to_upper_footprint_area_ratio"] = evidence[
                "maximum_layered_footprint_ratio"
            ]
            structure["lower_platform_passed"] = not evidence["triggered"]
            structure["lower_platform_evidence"] = (
                "generic_normalized_3d_layered_footprint+multiview_lower_silhouette"
            )
            if evidence["triggered"]:
                updated["hard_geometry_gate_passed"] = False
                updated["structure_gate_passed"] = False
    return updated


def tessellation_aware_platform_repair_policy(
    report: dict[str, Any],
    *,
    default_maximum_removed_face_fraction: float = 0.50,
    strong_evidence_maximum_removed_face_fraction: float = 0.85,
    minimum_strong_footprint_ratio: float = 8.0,
    minimum_strong_supporting_views: int = 4,
) -> dict[str, Any]:
    """Raise the face-count cap only for exceptionally strong platform evidence.

    Triangle count is not proportional to semantic importance: a flat generated
    platform can contain most of a uniformly remeshed asset's faces.  The relaxed
    cap therefore requires both a very large normalized 3D footprint anomaly and
    agreement in every horizontal turntable view.  The edit remains bounded by
    the independent low-height and post-repair regression gates.
    """

    evidence = report.get("generic_connected_platform_evidence") or {}
    footprint_ratio = float(
        evidence.get("lower_to_upper_footprint_area_ratio", 0.0) or 0.0
    )
    supporting_views = sorted(
        {str(axis) for axis in evidence.get("supporting_views", [])}
    )
    strong = bool(
        evidence.get("triggered")
        and footprint_ratio >= float(minimum_strong_footprint_ratio)
        and len(supporting_views) >= int(minimum_strong_supporting_views)
    )
    return {
        "schema": "scene_detail_tessellation_aware_repair_policy_v1",
        "strong_platform_evidence": strong,
        "maximum_removed_face_fraction": float(
            strong_evidence_maximum_removed_face_fraction
            if strong
            else default_maximum_removed_face_fraction
        ),
        "lower_to_upper_footprint_area_ratio": round(footprint_ratio, 6),
        "minimum_strong_footprint_ratio": float(minimum_strong_footprint_ratio),
        "supporting_views": supporting_views,
        "minimum_strong_supporting_views": int(minimum_strong_supporting_views),
        "height_bound_still_required": True,
        "post_repair_regression_gates_still_required": True,
        "category_independent": True,
    }


def broad_low_object_candidates(
    manifest: dict[str, Any],
    *,
    object_id: str,
    maximum_top_z_ratio: float = 0.28,
    maximum_height_ratio: float = 0.18,
    minimum_footprint_ratio: float = 0.55,
) -> list[dict[str, Any]]:
    """Find independently imported components shaped like a broad low platform.

    This is a category-independent 3D proposal, not a deletion decision.  It is
    intentionally conservative: an object must be wholly low, vertically thin,
    and broad relative to the complete asset.  Connected defects remain handled
    by the multi-view face path and the downstream hard verification gate.
    """

    evidence = manifest.get("geometry_evidence", {}).get(object_id, {})
    face_table_path = Path(str(evidence.get("face_table_path") or ""))
    if not face_table_path.is_file():
        return []
    table = np.load(face_table_path)
    object_index = np.asarray(table["object_index"], dtype=np.int32)
    centroids = np.asarray(table["centroid_xyz"], dtype=np.float32)
    maximum_z = np.asarray(table["maximum_z"], dtype=np.float32)
    if not len(centroids):
        return []
    names = [str(item) for item in evidence.get("object_names", [])]
    z_min = float(evidence.get("normalized_z_min", float(centroids[:, 2].min())))
    z_max = float(evidence.get("normalized_z_max", float(maximum_z.max())))
    height = max(z_max - z_min, 1e-8)
    full_x = max(float(np.ptp(centroids[:, 0])), 1e-8)
    full_y = max(float(np.ptp(centroids[:, 1])), 1e-8)
    full_area = full_x * full_y
    rows: list[dict[str, Any]] = []
    for index in sorted(set(object_index.tolist())):
        ids = np.flatnonzero(object_index == int(index))
        if len(ids) < 6:
            continue
        local = centroids[ids]
        top_ratio = (float(maximum_z[ids].max()) - z_min) / height
        bottom_ratio = (float(local[:, 2].min()) - z_min) / height
        object_height_ratio = max(0.0, top_ratio - bottom_ratio)
        footprint = float(np.ptp(local[:, 0])) * float(np.ptp(local[:, 1]))
        footprint_ratio = footprint / max(full_area, 1e-8)
        passes = bool(
            top_ratio <= float(maximum_top_z_ratio)
            and object_height_ratio <= float(maximum_height_ratio)
            and footprint_ratio >= float(minimum_footprint_ratio)
        )
        if passes:
            rows.append(
                {
                    "object_index": int(index),
                    "object_name": (
                        names[index] if 0 <= index < len(names) else f"object_{index}"
                    ),
                    "face_count": int(len(ids)),
                    "top_z_ratio": round(top_ratio, 6),
                    "height_ratio": round(object_height_ratio, 6),
                    "centroid_footprint_ratio": round(footprint_ratio, 6),
                }
            )
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lower_foreground_mask(
    image_path: Path,
    *,
    lower_start_ratio: float,
    target_size: tuple[int, int],
) -> tuple[np.ndarray, dict[str, Any]]:
    rgba = np.asarray(Image.open(image_path).convert("RGBA"), dtype=np.uint8)
    foreground = rgba[..., 3] > 16
    ys, xs = np.nonzero(foreground)
    if len(xs) == 0:
        return np.zeros(target_size, dtype=np.bool_), {
            "evaluated": False,
            "reason": "empty_foreground",
        }
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    lower_start = int(round(y0 + (y1 - y0) * float(lower_start_ratio)))
    rows = np.arange(foreground.shape[0], dtype=np.int32)[:, None]
    lower = foreground & (rows >= lower_start)
    mask_image = Image.fromarray((lower.astype(np.uint8) * 255), mode="L")
    resized = np.asarray(
        mask_image.resize((target_size[1], target_size[0]), Image.Resampling.NEAREST),
        dtype=np.uint8,
    ) > 0
    return resized, {
        "evaluated": True,
        "source_bbox_xyxy": [x0, y0, x1, y1],
        "lower_start_y": lower_start,
        "lower_start_ratio": round(float(lower_start_ratio), 6),
        "source_mask_pixel_count": int(np.count_nonzero(lower)),
        "evidence_mask_pixel_count": int(np.count_nonzero(resized)),
    }


def localize_lower_platform_faces(
    manifest: dict[str, Any],
    *,
    object_id: str,
    output_dir: Path,
    lower_start_ratio: float = 0.62,
    maximum_face_z_ratio: float = 0.28,
    minimum_pixels_per_face: int = 2,
    minimum_supporting_views: int = 2,
    minimum_projected_views_per_face: int = 1,
    maximum_removed_face_fraction: float = 0.50,
    repair_policy_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map lower-platform image evidence to stable imported mesh polygon IDs.

    The RGB detector only proposes a lower-image mask.  Face identity comes from
    aligned orthographic ray buffers, and a second 3D height gate prevents a
    low-image background or an elevated shoe upper from becoming editable.
    """

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    views = manifest.get("views", {}).get(object_id, {})
    evidence = manifest.get("geometry_evidence", {}).get(object_id, {})
    if not isinstance(evidence, dict) or not evidence.get("face_table_path"):
        raise ValueError(f"{object_id}: geometry evidence is missing")
    face_table_path = Path(str(evidence["face_table_path"])).resolve()
    table = np.load(face_table_path)
    object_index = np.asarray(table["object_index"], dtype=np.int32)
    polygon_index = np.asarray(table["polygon_index"], dtype=np.int32)
    centroid_xyz = np.asarray(table["centroid_xyz"], dtype=np.float32)
    maximum_z = np.asarray(table["maximum_z"], dtype=np.float32)
    z_min = float(evidence["normalized_z_min"])
    z_max = float(evidence["normalized_z_max"])
    height = max(z_max - z_min, 1e-8)
    maximum_z_ratio = (maximum_z - z_min) / height
    low_geometry = maximum_z_ratio <= float(maximum_face_z_ratio)
    broad_low_candidates = broad_low_object_candidates(
        manifest,
        object_id=object_id,
        maximum_top_z_ratio=maximum_face_z_ratio,
    )
    broad_low_object_indices = {
        int(item["object_index"]) for item in broad_low_candidates
    }

    face_pixels: defaultdict[int, int] = defaultdict(int)
    face_views: defaultdict[int, set[str]] = defaultdict(set)
    projected_face_views: defaultdict[int, set[str]] = defaultdict(set)
    view_reports: dict[str, Any] = {}
    mask_paths: dict[str, str] = {}
    for axis in VIEW_AXES:
        image_path = Path(str(views.get(axis) or ""))
        view_evidence = evidence.get("views", {}).get(axis, {})
        evidence_path = Path(str(view_evidence.get("path") or ""))
        if not image_path.is_file() or not evidence_path.is_file():
            view_reports[axis] = {
                "evaluated": False,
                "reason": "rgb_or_geometry_evidence_missing",
            }
            continue
        raster = np.load(evidence_path)
        face_map = np.asarray(raster["face_index"], dtype=np.int32)
        mask, mask_report = _lower_foreground_mask(
            image_path,
            lower_start_ratio=float(lower_start_ratio),
            target_size=face_map.shape,
        )
        valid = mask & (face_map >= 0)
        ids, counts = np.unique(face_map[valid], return_counts=True)
        supported = []
        for raw_id, raw_count in zip(ids.tolist(), counts.tolist()):
            face_id = int(raw_id)
            if face_id < 0 or face_id >= len(low_geometry) or not low_geometry[face_id]:
                continue
            count = int(raw_count)
            face_pixels[face_id] += count
            face_views[face_id].add(axis)
            supported.append(face_id)

        camera_matrix = np.asarray(
            view_evidence.get("camera_matrix_world"), dtype=np.float64
        )
        orthographic_scale = float(view_evidence.get("orthographic_scale") or 0.0)
        projected_supported: list[int] = []
        if camera_matrix.shape == (4, 4) and orthographic_scale > 0.0:
            world_to_camera = np.linalg.inv(camera_matrix)
            homogeneous = np.concatenate(
                [centroid_xyz.astype(np.float64), np.ones((len(centroid_xyz), 1))],
                axis=1,
            )
            camera_centroids = homogeneous @ world_to_camera.T
            rows = np.floor(
                (0.5 - camera_centroids[:, 1] / orthographic_scale)
                * face_map.shape[0]
            ).astype(np.int32)
            cols = np.floor(
                (camera_centroids[:, 0] / orthographic_scale + 0.5)
                * face_map.shape[1]
            ).astype(np.int32)
            inside = (
                (rows >= 0)
                & (rows < face_map.shape[0])
                & (cols >= 0)
                & (cols < face_map.shape[1])
                & low_geometry
            )
            inside_ids = np.flatnonzero(inside)
            for raw_id in inside_ids[mask[rows[inside_ids], cols[inside_ids]]].tolist():
                face_id = int(raw_id)
                projected_face_views[face_id].add(axis)
                projected_supported.append(face_id)
        mask_path = output_dir / f"{axis.replace('+', 'plus_').replace('-', 'minus_')}_lower_mask.png"
        Image.fromarray((mask.astype(np.uint8) * 255), mode="L").save(mask_path)
        mask_paths[axis] = str(mask_path)
        view_reports[axis] = {
            **mask_report,
            "rgb_path": str(image_path.resolve()),
            "geometry_evidence_path": str(evidence_path.resolve()),
            "low_face_hit_count": len(set(supported)),
            "low_face_centroid_projection_count": len(set(projected_supported)),
            "rgb_sha256": _sha256(image_path),
            "geometry_evidence_sha256": _sha256(evidence_path),
        }

    seed_face_ids = sorted(
        face_id
        for face_id in range(len(low_geometry))
        if low_geometry[face_id]
        and (
            face_pixels.get(face_id, 0) >= int(minimum_pixels_per_face)
            or len(projected_face_views.get(face_id, set()))
            >= int(minimum_projected_views_per_face)
        )
    )
    if broad_low_object_indices:
        seed_face_ids = [
            face_id
            for face_id in seed_face_ids
            if int(object_index[face_id]) in broad_low_object_indices
        ]
    supporting_axes = sorted(
        {
            axis
            for face_id in seed_face_ids
            for axis in (
                face_views.get(face_id, set())
                | projected_face_views.get(face_id, set())
            )
        }
    )
    object_names = [str(item) for item in evidence.get("object_names", [])]
    normalization = manifest.get("normalization", {}).get(object_id, {})
    root_matrix_world = normalization.get("root_matrix_world")
    if not isinstance(root_matrix_world, list) or len(root_matrix_world) != 4:
        raise ValueError(f"{object_id}: normalization root matrix is missing")
    selected_by_object: defaultdict[str, list[int]] = defaultdict(list)
    for face_id in seed_face_ids:
        index = int(object_index[face_id])
        name = object_names[index] if 0 <= index < len(object_names) else f"object_{index}"
        selected_by_object[name].append(int(polygon_index[face_id]))

    confidence = min(1.0, len(supporting_axes) / max(1, len(VIEW_AXES)))
    multi_view_confirmed = len(supporting_axes) >= int(minimum_supporting_views)
    result = {
        "schema": "scene_detail_face_localization_v2",
        "object_id": object_id,
        "issue_type": "forbidden_platform",
        "evidence_grounded": True,
        "multi_view_confirmed": multi_view_confirmed,
        "confidence": round(confidence, 6),
        "supporting_views": supporting_axes,
        "minimum_supporting_views": int(minimum_supporting_views),
        "minimum_projected_views_per_face": int(
            minimum_projected_views_per_face
        ),
        "seed_face_count": len(seed_face_ids),
        "seed_pixel_count": int(sum(face_pixels[item] for item in seed_face_ids)),
        "visible_seed_face_count": sum(
            face_pixels.get(item, 0) >= int(minimum_pixels_per_face)
            for item in seed_face_ids
        ),
        "projected_seed_face_count": sum(
            len(projected_face_views.get(item, set()))
            >= int(minimum_projected_views_per_face)
            for item in seed_face_ids
        ),
        "selected_seed_polygons": dict(selected_by_object),
        "broad_low_object_candidates": broad_low_candidates,
        "seed_filter": (
            "broad_low_independent_object_components"
            if broad_low_object_indices
            else "multiview_low_face_fallback_for_connected_geometry"
        ),
        "mask_paths": mask_paths,
        "view_reports": view_reports,
        "face_table_path": str(face_table_path),
        "face_table_sha256": _sha256(face_table_path),
        "geometry_limits": {
            "normalized_z_min": z_min,
            "normalized_z_max": z_max,
            "maximum_face_z_ratio": round(float(maximum_face_z_ratio), 6),
            "minimum_projected_views_per_face": int(
                minimum_projected_views_per_face
            ),
        },
        "normalization_root_matrix": root_matrix_world,
        "repair_policy": {
            "operation": "delete_seed_connected_low_region_and_fill_new_boundary",
            "expand_only_across_shared_edges": True,
            "maximum_face_z_ratio": round(float(maximum_face_z_ratio), 6),
            "maximum_removed_face_fraction": float(
                maximum_removed_face_fraction
            ),
            "requires_material_preservation": True,
            "tessellation_aware_policy_evidence": deepcopy(
                repair_policy_evidence
            ),
        },
        "accepted_for_automatic_repair": bool(seed_face_ids and multi_view_confirmed),
        "limitations": [
            "lower-image masks are category-independent proposals, not semantic part labels",
            "an individual low face needs one projected mask hit, while automatic repair still requires the defect region to be confirmed across multiple views",
            "every admitted face must remain fully below the stricter normalized height limit before connected expansion",
        ],
    }
    (output_dir / "face_localization.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return result
