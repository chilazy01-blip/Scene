from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage


RENDER_PROFILE_SCHEMA = "codex_trellis_render_profile_v1"
SHOWCASE_QUALITY_SCHEMA = "codex_trellis_showcase_quality_audit_v1"

RENDER_PROFILES: dict[str, dict[str, Any]] = {
    "relationship_evidence": {
        "schema": RENDER_PROFILE_SCHEMA,
        "name": "relationship_evidence",
        "purpose": "unambiguous close-up geometry relationship evidence",
        "engine": "BLENDER_EEVEE_NEXT",
        "resolution": [768, 768],
        "samples": 64,
        "denoise": False,
        "view_transform": "AgX",
        "look": "AgX - Medium High Contrast",
        "exposure": 0.0,
        "white_balance_kelvin": 5500,
        "material_scale_m": 1.0,
        "isolated_relation_objects": True,
    },
    "final_showcase": {
        "schema": RENDER_PROFILE_SCHEMA,
        "name": "final_showcase",
        "purpose": "presentation-quality whole-scene views after semantic acceptance",
        "engine": "CYCLES",
        "resolution": [1024, 768],
        "samples": 64,
        "denoise": True,
        "view_transform": "AgX",
        "look": "AgX - Medium High Contrast",
        "exposure": 0.15,
        "white_balance_kelvin": 5200,
        "material_scale_m": 1.0,
        "isolated_relation_objects": False,
    },
}


def validate_render_profiles(profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    required = {"relationship_evidence", "final_showcase"}
    if set(profiles) != required:
        errors.append(f"profiles must be exactly {sorted(required)}")
    for name in sorted(required & set(profiles)):
        profile = profiles[name]
        if profile.get("schema") != RENDER_PROFILE_SCHEMA:
            errors.append(f"{name}.schema is invalid")
        if profile.get("name") != name:
            errors.append(f"{name}.name is invalid")
        resolution = profile.get("resolution")
        if not (
            isinstance(resolution, list)
            and len(resolution) == 2
            and all(isinstance(value, int) and value >= 256 for value in resolution)
        ):
            errors.append(f"{name}.resolution is invalid")
        if int(profile.get("samples", 0)) < 16:
            errors.append(f"{name}.samples must be at least 16")
        if profile.get("view_transform") not in {"AgX", "Filmic"}:
            errors.append(f"{name}.view_transform must be AgX or Filmic")
        if not 4000 <= int(profile.get("white_balance_kelvin", 0)) <= 7000:
            errors.append(f"{name}.white_balance_kelvin is outside the production range")
        if float(profile.get("material_scale_m", 0.0)) <= 0.0:
            errors.append(f"{name}.material_scale_m must be positive")
    if profiles.get("relationship_evidence") == profiles.get("final_showcase"):
        errors.append("relationship evidence and final showcase profiles must be distinct")
    if profiles.get("final_showcase", {}).get("engine") != "CYCLES":
        errors.append("final_showcase.engine must be CYCLES")
    if profiles.get("final_showcase", {}).get("denoise") is not True:
        errors.append("final_showcase.denoise must be true")
    return {"ok": not errors, "errors": errors}


def score_camera_candidate(
    candidate: dict[str, Any],
    *,
    required_object_ids: set[str],
    relation_pairs: list[tuple[str, str]],
    minimum_visible_pixels: int = 12,
) -> dict[str, Any]:
    observations = candidate.get("objects", {})
    observations = observations if isinstance(observations, dict) else {}
    visible = {
        object_id
        for object_id in required_object_ids
        if int(observations.get(object_id, {}).get("visible_pixels", 0))
        >= minimum_visible_pixels
    }
    complete = {
        object_id
        for object_id in visible
        if observations.get(object_id, {}).get("projection_inside_frame") is True
        and observations.get(object_id, {}).get("touches_image_border") is not True
    }
    relation_visible = [
        [source, target]
        for source, target in relation_pairs
        if source in visible and target in visible
    ]
    cropped = {
        object_id
        for object_id in visible
        if observations.get(object_id, {}).get("touches_image_border") is True
        or observations.get(object_id, {}).get("projection_inside_frame") is not True
    }
    denominator = max(1, len(required_object_ids))
    relation_denominator = max(1, len(relation_pairs))
    coverage = len(visible) / denominator
    complete_coverage = len(complete) / denominator
    relation_coverage = len(relation_visible) / relation_denominator
    occupancy = float(candidate.get("scene_occupancy_fraction", 0.0) or 0.0)
    centeredness = float(candidate.get("visible_centroid_centeredness", 0.0) or 0.0)
    occupancy_preference = max(0.0, 1.0 - abs(occupancy - 0.58) / 0.58)
    score = (
        5.0 * coverage
        + 3.0 * complete_coverage
        + 2.5 * relation_coverage
        + 0.8 * centeredness
        + 0.5 * occupancy_preference
        - 1.5 * len(cropped) / denominator
    )
    return {
        "score": round(score, 8),
        "visible_required_ids": sorted(visible),
        "complete_required_ids": sorted(complete),
        "cropped_required_ids": sorted(cropped),
        "visible_relation_pairs": relation_visible,
        "required_coverage": coverage,
        "complete_coverage": complete_coverage,
        "relation_coverage": relation_coverage,
        "scene_occupancy_fraction": occupancy,
        "visible_centroid_centeredness": centeredness,
    }


def select_camera_pair(
    candidates: list[dict[str, Any]],
    *,
    required_object_ids: set[str],
    relation_pairs: list[tuple[str, str]],
) -> dict[str, Any]:
    if len(candidates) < 2:
        raise ValueError("at least two camera candidates are required")
    scored = []
    for candidate in candidates:
        row = dict(candidate)
        row["score_report"] = score_camera_candidate(
            row,
            required_object_ids=required_object_ids,
            relation_pairs=relation_pairs,
        )
        scored.append(row)
    best: tuple[tuple[float, ...], dict[str, Any], dict[str, Any]] | None = None
    relation_set = {tuple(pair) for pair in relation_pairs}
    for first_index, first in enumerate(scored):
        for second in scored[first_index + 1 :]:
            first_score = first["score_report"]
            second_score = second["score_report"]
            visible = set(first_score["visible_required_ids"]) | set(
                second_score["visible_required_ids"]
            )
            complete = set(first_score["complete_required_ids"]) | set(
                second_score["complete_required_ids"]
            )
            relations = {
                tuple(pair)
                for pair in first_score["visible_relation_pairs"]
                + second_score["visible_relation_pairs"]
            }
            different_side = first.get("room_side") != second.get("room_side")
            objective = (
                len(visible) / max(1, len(required_object_ids)),
                len(complete) / max(1, len(required_object_ids)),
                len(relations & relation_set) / max(1, len(relation_set)),
                float(different_side),
                float(first_score["score"]) + float(second_score["score"]),
            )
            if best is None or objective > best[0]:
                best = (objective, first, second)
    assert best is not None
    selected = sorted(
        (best[1], best[2]),
        key=lambda item: float(item["score_report"]["score"]),
        reverse=True,
    )
    return {
        "selected_candidate_ids": [str(item["id"]) for item in selected],
        "pair_objective": {
            "required_coverage": best[0][0],
            "complete_coverage": best[0][1],
            "relation_coverage": best[0][2],
            "different_room_side": bool(best[0][3]),
            "individual_score_sum": best[0][4],
        },
        "candidates": sorted(
            scored,
            key=lambda item: float(item["score_report"]["score"]),
            reverse=True,
        ),
    }


def image_quality_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    luminance = (
        0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    )
    denoised = ndimage.median_filter(luminance, size=3, mode="reflect")
    gradient_x = np.abs(np.diff(denoised, axis=1, prepend=denoised[:, :1]))
    gradient_y = np.abs(np.diff(denoised, axis=0, prepend=denoised[:1, :]))
    flat = (gradient_x + gradient_y < 0.025) & (luminance > 0.08) & (luminance < 0.92)
    residual = np.abs(luminance - denoised)
    return {
        "path": str(path),
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "overexposed_fraction": float(np.mean(luminance >= 0.985)),
        "near_black_fraction": float(np.mean(luminance <= 0.008)),
        "midtone_fraction": float(np.mean((luminance >= 0.08) & (luminance <= 0.92))),
        "flat_region_noise_mean": float(np.mean(residual[flat])) if np.any(flat) else None,
        "flat_region_pixel_count": int(np.count_nonzero(flat)),
        "mean_luminance": float(np.mean(luminance)),
    }


def masked_luminance_metrics(
    rgb_path: Path,
    mask_path: Path,
    *,
    pass_index: int,
    object_index_denominator: int,
) -> dict[str, Any]:
    with Image.open(rgb_path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    with Image.open(mask_path) as image:
        mask_values = np.asarray(image.convert("L"), dtype=np.float32)
    if mask_values.shape != rgb.shape[:2]:
        raise ValueError("object-index mask and RGB dimensions must match")
    target = 255.0 * pass_index / max(1, object_index_denominator)
    tolerance = max(2.0, 255.0 / max(1, object_index_denominator) / 3.0)
    mask = np.abs(mask_values - target) <= tolerance
    if not np.any(mask):
        return {"pixel_count": 0, "near_black_fraction": None, "mean_luminance": None}
    luminance = (
        0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    )[mask]
    return {
        "pixel_count": int(np.count_nonzero(mask)),
        "near_black_fraction": float(np.mean(luminance <= 0.015)),
        "mean_luminance": float(np.mean(luminance)),
    }


def evaluate_showcase_quality(
    manifest: dict[str, Any],
    *,
    maximum_overexposed_fraction: float = 0.06,
    maximum_near_black_fraction: float = 0.20,
    maximum_window_near_black_fraction: float = 0.35,
    maximum_flat_region_noise_mean: float = 0.025,
) -> dict[str, Any]:
    profile_validation = validate_render_profiles(manifest.get("profiles", {}))
    selected = manifest.get("selected_views", [])
    selected = selected if isinstance(selected, list) else []
    view_reports = []
    failures: list[dict[str, Any]] = []
    for row in selected:
        path = Path(str(row.get("rgb_path") or ""))
        if not path.is_file():
            failures.append({"type": "missing_showcase_rgb", "view": row.get("id")})
            continue
        metrics = image_quality_metrics(path)
        metrics["id"] = row.get("id")
        metrics["cropped_required_ids"] = list(row.get("cropped_required_ids", []))
        window_observation = row.get("object_mask_observations", {}).get(
            "window_main", {}
        )
        if int(window_observation.get("visible_pixels", 0)) >= 12:
            mask_path = Path(str(row.get("object_index_mask_path") or ""))
            if not mask_path.is_file():
                failures.append({"type": "missing_window_mask", "view": row.get("id")})
            else:
                window_metrics = masked_luminance_metrics(
                    path,
                    mask_path,
                    pass_index=int(window_observation["pass_index"]),
                    object_index_denominator=int(row["object_index_denominator"]),
                )
                metrics["window_main"] = window_metrics
                black_fraction = window_metrics["near_black_fraction"]
                if (
                    black_fraction is not None
                    and black_fraction > maximum_window_near_black_fraction
                ):
                    failures.append(
                        {"type": "pure_black_window", "view": row.get("id")}
                    )
        if metrics["overexposed_fraction"] > maximum_overexposed_fraction:
            failures.append({"type": "overexposure", "view": row.get("id")})
        if metrics["near_black_fraction"] > maximum_near_black_fraction:
            failures.append({"type": "excessive_near_black", "view": row.get("id")})
        noise = metrics["flat_region_noise_mean"]
        if noise is None or noise > maximum_flat_region_noise_mean:
            failures.append({"type": "excessive_flat_region_noise", "view": row.get("id")})
        if metrics["cropped_required_ids"]:
            failures.append(
                {
                    "type": "required_object_cropped",
                    "view": row.get("id"),
                    "objects": metrics["cropped_required_ids"],
                }
            )
        view_reports.append(metrics)
    selection = manifest.get("camera_selection", {})
    objective = selection.get("pair_objective", {}) if isinstance(selection, dict) else {}
    if float(objective.get("required_coverage", 0.0)) < 1.0:
        failures.append({"type": "selected_pair_required_coverage"})
    if float(objective.get("relation_coverage", 0.0)) < 1.0:
        failures.append({"type": "selected_pair_relation_coverage"})
    if not profile_validation["ok"]:
        failures.extend(
            {"type": "render_profile", "reason": error}
            for error in profile_validation["errors"]
        )
    return {
        "schema": SHOWCASE_QUALITY_SCHEMA,
        "ok": bool(selected) and not failures,
        "profile_validation": profile_validation,
        "thresholds": {
            "maximum_overexposed_fraction": maximum_overexposed_fraction,
            "maximum_near_black_fraction": maximum_near_black_fraction,
            "maximum_window_near_black_fraction": maximum_window_near_black_fraction,
            "maximum_flat_region_noise_mean": maximum_flat_region_noise_mean,
            "selected_pair_required_coverage": 1.0,
            "selected_pair_relation_coverage": 1.0,
        },
        "views": view_reports,
        "camera_selection": {
            "selected_candidate_ids": list(selection.get("selected_candidate_ids", [])),
            "pair_objective": objective,
        },
        "failures": failures,
        "manual_review_required": True,
        "limitations": [
            "flat-region residual is an image-space noise proxy, not a path-tracer variance pass",
            "camera crop uses final object-index masks plus projected bounds",
            "manual review remains required for composition and material plausibility",
        ],
    }


def write_profile_contract(path: Path) -> None:
    path.write_text(
        json.dumps(RENDER_PROFILES, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
