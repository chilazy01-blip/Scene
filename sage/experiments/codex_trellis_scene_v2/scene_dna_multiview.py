from __future__ import annotations

import json
import math
import subprocess
from collections import deque
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


VIEW_AXES = ("+x", "-x", "+y", "-y")
PALETTE_RGB: dict[str, tuple[int, int, int]] = {
    "white": (238, 238, 232),
    "black": (32, 32, 32),
    "beige": (210, 190, 158),
    "gray": (135, 135, 135),
    "blue": (55, 92, 155),
    "green": (80, 125, 82),
    "red": (165, 58, 48),
    "oak": (181, 132, 78),
    "walnut": (92, 58, 38),
    "wood": (164, 112, 67),
    "brass": (184, 145, 62),
}

def _connected_component_areas(mask: np.ndarray) -> list[int]:
    """Return 8-connected foreground areas without requiring scipy in production."""

    height, width = mask.shape
    visited = np.zeros(mask.shape, dtype=np.bool_)
    areas: list[int] = []
    for y, x in zip(*np.nonzero(mask)):
        if visited[y, x]:
            continue
        queue: deque[tuple[int, int]] = deque([(int(y), int(x))])
        visited[y, x] = True
        area = 0
        while queue:
            cy, cx = queue.popleft()
            area += 1
            for ny in range(max(0, cy - 1), min(height, cy + 2)):
                for nx in range(max(0, cx - 1), min(width, cx + 2)):
                    if mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
        areas.append(area)
    return sorted(areas, reverse=True)


def _internal_hole_ratio(mask: np.ndarray) -> float:
    """Measure background enclosed by a silhouette, excluding outside background."""

    height, width = mask.shape
    background = ~mask
    exterior = np.zeros(mask.shape, dtype=np.bool_)
    queue: deque[tuple[int, int]] = deque()
    for x in range(width):
        if background[0, x]:
            queue.append((0, x))
        if background[height - 1, x]:
            queue.append((height - 1, x))
    for y in range(height):
        if background[y, 0]:
            queue.append((y, 0))
        if background[y, width - 1]:
            queue.append((y, width - 1))
    while queue:
        y, x = queue.popleft()
        if exterior[y, x] or not background[y, x]:
            continue
        exterior[y, x] = True
        for ny in range(max(0, y - 1), min(height, y + 2)):
            for nx in range(max(0, x - 1), min(width, x + 2)):
                if background[ny, nx] and not exterior[ny, nx]:
                    queue.append((ny, nx))
    holes = background & ~exterior
    return float(np.count_nonzero(holes)) / float(max(1, mask.size))


def structure_profile_for_object(
    obj: dict[str, Any],
    semantic_form_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile silhouette expectations from shape language, not category names."""

    semantic_form_contract = (
        semantic_form_contract if isinstance(semantic_form_contract, dict) else {}
    )
    semantic_profile = str(
        semantic_form_contract.get("shape_profile") or ""
    ).strip()
    # Some legitimate objects are assemblies whose projected parts need not
    # touch (casters, chair bases, open frames).  Their contract must therefore
    # be allowed to relax only the fragmentation threshold; compact objects and
    # lamps retain strict thresholds so cords/platforms still fail.
    semantic_profiles = {
        "skeletal_support": {
            "profile": "skeletal_support",
            "compact_silhouette_required": False,
            "minimum_bbox_fill": None,
            "maximum_detached_ratio": 0.26,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:skeletal_support",
        },
        "slender_radial": {
            "profile": "slender_radial",
            "compact_silhouette_required": False,
            "minimum_bbox_fill": None,
            "maximum_detached_ratio": 0.04,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": 1.8,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:slender_radial",
        },
        "organic_branching": {
            "profile": "organic_branching",
            "compact_silhouette_required": False,
            "minimum_bbox_fill": None,
            "maximum_detached_ratio": 0.10,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:organic_branching",
        },
        "compact_orthogonal": {
            "profile": "compact_orthogonal",
            "compact_silhouette_required": True,
            "minimum_bbox_fill": 0.88,
            "maximum_detached_ratio": 0.0075,
            "maximum_internal_hole_ratio": 0.004,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:compact_orthogonal",
        },
        "compact_layered": {
            "profile": "compact_layered",
            "compact_silhouette_required": True,
            "minimum_bbox_fill": 0.70,
            "maximum_detached_ratio": 0.02,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:compact_layered",
        },
        "open_repeated_frame": {
            "profile": "open_repeated_frame",
            "compact_silhouette_required": False,
            "minimum_bbox_fill": None,
            "maximum_detached_ratio": 0.08,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "semantic_form_contract:open_repeated_frame",
        },
        "open_back_footwear": {
            "profile": "open_back_footwear",
            "compact_silhouette_required": False,
            "minimum_bbox_fill": None,
            "maximum_detached_ratio": 0.08,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": 0.80,
            "maximum_lower_to_upper_footprint_area_ratio": 2.80,
            "evidence": "semantic_form_contract:open_back_footwear",
        },
    }
    if semantic_profile in semantic_profiles:
        return deepcopy(semantic_profiles[semantic_profile])

    generation_spec = obj.get("asset_generation_spec")
    generation_spec = generation_spec if isinstance(generation_spec, dict) else {}
    guidance = str(generation_spec.get("shape_guidance") or "").strip().lower()
    if "closed rectangular" in guidance and "straight edges" in guidance:
        return {
            "profile": "compact_orthogonal",
            "compact_silhouette_required": True,
            "minimum_bbox_fill": 0.88,
            "maximum_detached_ratio": 0.0075,
            "maximum_internal_hole_ratio": 0.004,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "shape_guidance:closed rectangular+straight edges",
        }
    if "compact stack" in guidance:
        return {
            "profile": "compact_layered",
            "compact_silhouette_required": True,
            "minimum_bbox_fill": 0.70,
            "maximum_detached_ratio": 0.02,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "shape_guidance:compact stack",
        }
    if "soft rectangular" in guidance:
        return {
            "profile": "compact_rounded_soft",
            "compact_silhouette_required": True,
            "minimum_bbox_fill": 0.72,
            "maximum_detached_ratio": 0.015,
            "maximum_internal_hole_ratio": None,
            "maximum_lower_overhang_ratio": None,
            "maximum_lower_full_width_row_fraction": None,
            "evidence": "shape_guidance:soft rectangular",
        }
    return {
        "profile": "general_object",
        "compact_silhouette_required": False,
        "minimum_bbox_fill": None,
        "maximum_detached_ratio": 0.08,
        "maximum_internal_hole_ratio": None,
        "maximum_lower_overhang_ratio": None,
        "maximum_lower_full_width_row_fraction": None,
        "evidence": "no compact shape-language contract",
    }


def _desired_tags(contract: dict[str, Any], object_id: str) -> set[str]:
    tags = {
        str(item.get("tag") or "").strip().lower()
        for item in contract.get("global_profile", {}).get("desired_tags", [])
        if isinstance(item, dict) and item.get("tag")
    }
    profile = contract.get("object_profiles", {}).get(object_id, {})
    tags.update(
        str(item).strip().lower()
        for item in profile.get("individuality_tags", [])
        if str(item).strip()
    )
    return tags


def _individuality_tags(contract: dict[str, Any], object_id: str) -> set[str]:
    profile = contract.get("object_profiles", {}).get(object_id, {})
    return {
        str(item).strip().lower()
        for item in profile.get("individuality_tags", [])
        if str(item).strip()
    }


def _image_features(
    image_path: Path,
    desired_tags: set[str],
    *,
    alpha_threshold: int = 24,
    priority_palette_tags: set[str] | None = None,
) -> dict[str, Any]:
    rgba = np.asarray(Image.open(image_path).convert("RGBA"), dtype=np.uint8)
    foreground = rgba[:, :, 3] > alpha_threshold
    height, width = foreground.shape
    ys, xs = np.nonzero(foreground)
    if not len(xs):
        return {
            "ok": False,
            "reason": "empty_foreground",
            "image_path": str(image_path),
            "style_score": 0.0,
        }
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    bbox_width, bbox_height = x1 - x0, y1 - y0
    bbox_mask = foreground[y0:y1, x0:x1]
    row_occupancy = np.mean(bbox_mask, axis=1)
    if bbox_height <= 1:
        upper_rows = row_occupancy
        lower_rows = row_occupancy
    else:
        lower_start = max(
            1, min(bbox_height - 1, int(math.floor(bbox_height * 0.70)))
        )
        upper_rows = row_occupancy[:lower_start]
        lower_rows = row_occupancy[lower_start:]
    lower_overhang_ratio = float(np.max(lower_rows)) / float(
        max(1.0 / float(max(1, bbox_width)), float(np.max(upper_rows)))
    )
    lower_full_width_row_fraction = float(np.mean(lower_rows >= 0.90))
    internal_hole_ratio = _internal_hole_ratio(bbox_mask)
    component_areas = _connected_component_areas(foreground)
    largest_component_ratio = float(component_areas[0]) / float(max(1, len(xs)))
    detached_component_ratio = 1.0 - largest_component_ratio
    meaningful_component_count = sum(
        area >= max(25, int(len(xs) * 0.0025)) for area in component_areas
    )
    pixels = rgba[:, :, :3][foreground].astype(np.float32)
    if len(pixels) > 50_000:
        pixels = pixels[:: max(1, len(pixels) // 50_000)][:50_000]
    foreground_ratio = float(len(xs)) / float(width * height)
    border = np.concatenate(
        (foreground[0], foreground[-1], foreground[:, 0], foreground[:, -1])
    )
    border_ratio = float(np.count_nonzero(border)) / float(max(1, border.size))

    palette_scores: dict[str, float] = {}
    max_distance = math.sqrt(3.0) * 255.0
    local_palette_tags = (priority_palette_tags or set()) & set(PALETTE_RGB)
    palette_target_tags = local_palette_tags or (desired_tags & set(PALETTE_RGB))
    for tag in sorted(palette_target_tags):
        target = np.asarray(PALETTE_RGB[tag], dtype=np.float32)
        distances = np.linalg.norm(pixels - target, axis=1)
        representative = float(np.percentile(distances, 20.0))
        palette_scores[tag] = round(
            max(0.0, min(1.0, 1.0 - representative / max_distance)), 6
        )
    palette_score = max(palette_scores.values(), default=0.5)

    mean_rgb = pixels.mean(axis=0)
    warmth_index = float((mean_rgb[0] - mean_rgb[2]) / 255.0)
    if "warm" in desired_tags and "cool" not in desired_tags:
        temperature_score = max(0.0, min(1.0, 0.5 + warmth_index))
        temperature_target = "warm"
    elif "cool" in desired_tags and "warm" not in desired_tags:
        temperature_score = max(0.0, min(1.0, 0.5 - warmth_index))
        temperature_target = "cool"
    else:
        temperature_score = 0.5
        temperature_target = "unspecified"

    gray = (
        rgba[:, :, 0].astype(np.float32) * 0.299
        + rgba[:, :, 1].astype(np.float32) * 0.587
        + rgba[:, :, 2].astype(np.float32) * 0.114
    )
    horizontal_valid = foreground[:, 1:] & foreground[:, :-1]
    vertical_valid = foreground[1:, :] & foreground[:-1, :]
    horizontal_edges = np.abs(gray[:, 1:] - gray[:, :-1]) > 18.0
    vertical_edges = np.abs(gray[1:, :] - gray[:-1, :]) > 18.0
    valid_count = int(horizontal_valid.sum()) + int(vertical_valid.sum())
    edge_count = int((horizontal_edges & horizontal_valid).sum()) + int(
        (vertical_edges & vertical_valid).sum()
    )
    edge_density = float(edge_count) / float(max(1, valid_count))
    detail_score = max(0.0, min(1.0, 1.0 - abs(edge_density - 0.08) / 0.18))
    style_score = 0.55 * palette_score + 0.20 * temperature_score + 0.25 * detail_score
    structure_ok = 0.02 <= foreground_ratio <= 0.85 and border_ratio <= 0.02
    return {
        "ok": structure_ok,
        "image_path": str(image_path),
        "foreground_ratio": round(foreground_ratio, 6),
        "border_foreground_ratio": round(border_ratio, 6),
        "bbox": [x0, y0, x1, y1],
        "bbox_aspect_ratio": round(float(bbox_width) / float(max(1, bbox_height)), 6),
        "bbox_fill_ratio": round(float(np.mean(bbox_mask)), 6),
        "internal_hole_ratio": round(internal_hole_ratio, 6),
        "lower_overhang_ratio": round(lower_overhang_ratio, 6),
        "lower_full_width_row_fraction": round(lower_full_width_row_fraction, 6),
        "connected_component_count": len(component_areas),
        "meaningful_component_count": int(meaningful_component_count),
        "largest_component_ratio": round(largest_component_ratio, 6),
        "detached_component_ratio": round(detached_component_ratio, 6),
        "mean_foreground_rgb": [round(float(value), 3) for value in mean_rgb],
        "palette_score": round(palette_score, 6),
        "palette_tag_scores": palette_scores,
        "palette_target_source": (
            "object_individuality" if local_palette_tags else "global_profile"
        ),
        "temperature_score": round(temperature_score, 6),
        "temperature_target": temperature_target,
        "warmth_index": round(warmth_index, 6),
        "detail_score": round(detail_score, 6),
        "edge_density": round(edge_density, 6),
        "style_score": round(style_score, 6),
    }


def _opposite_view_consistency(features: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pair_scores: dict[str, float] = {}
    for left, right in (("+x", "-x"), ("+y", "-y")):
        left_ratio = float(features.get(left, {}).get("bbox_aspect_ratio", 0.0))
        right_ratio = float(features.get(right, {}).get("bbox_aspect_ratio", 0.0))
        if left_ratio <= 0.0 or right_ratio <= 0.0:
            score = 0.0
        else:
            score = math.exp(-abs(math.log(left_ratio / right_ratio)))
        pair_scores[f"{left}:{right}"] = round(score, 6)
    minimum = min(pair_scores.values(), default=0.0)
    return {
        "pair_scores": pair_scores,
        "minimum_pair_score": round(minimum, 6),
        "passes": minimum >= 0.65,
    }


def _reference_appearance_score(
    reference_image_path: Path | None,
    view_features: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if reference_image_path is None or not reference_image_path.is_file():
        return {"evaluated": False, "score": None, "reason": "reference_rgba_unavailable"}
    reference = _image_features(reference_image_path, set())
    if not reference.get("mean_foreground_rgb"):
        return {"evaluated": False, "score": None, "reason": "reference_foreground_unavailable"}
    means = [
        np.asarray(item["mean_foreground_rgb"], dtype=np.float32)
        for item in view_features.values()
        if item.get("mean_foreground_rgb")
    ]
    if not means:
        return {"evaluated": False, "score": None, "reason": "render_foreground_unavailable"}
    rendered_mean = np.mean(np.stack(means), axis=0)
    reference_mean = np.asarray(reference["mean_foreground_rgb"], dtype=np.float32)
    distance = float(np.linalg.norm(rendered_mean - reference_mean))
    score = max(0.0, min(1.0, 1.0 - distance / (math.sqrt(3.0) * 255.0)))
    return {
        "evaluated": True,
        "score": round(score, 6),
        "reference_image_path": str(reference_image_path),
        "reference_mean_rgb": reference["mean_foreground_rgb"],
        "rendered_mean_rgb": [round(float(value), 3) for value in rendered_mean],
        "method": "foreground_mean_rgb_distance",
        "limitations": "appearance color consistency only; not category or semantic style similarity",
    }


def _semantic_style_multiview_score(
    view_features: dict[str, dict[str, Any]],
    *,
    semantic_scorer: Any | None,
    semantic_form_contract: dict[str, Any],
    desired_tags: set[str],
) -> dict[str, Any]:
    if semantic_scorer is None:
        return {
            "evaluated": False,
            "semantic_category_verified": False,
            "style_alignment_verified": False,
            "reason": "semantic_scorer_not_configured",
        }
    identity = str(
        semantic_form_contract.get("identity") or "object"
    ).replace("_", " ")
    style_tags = sorted(
        tag for tag in desired_tags if tag not in {"wood", "oak", "walnut", "fabric", "leather", "metal", "glass", "ceramic", "brass", "paper", "rubber"}
    )
    style_phrase = ", ".join(tag.replace("_", " ") for tag in style_tags)
    opposite_tags: set[str] = set()
    opposites = {
        "warm": "cool",
        "cool": "warm",
        "modern": "classic",
        "classic": "modern",
        "minimal": "ornate",
        "ornate": "minimal",
        "industrial": "ornate traditional",
    }
    for tag in style_tags:
        if tag in opposites:
            opposite_tags.add(opposites[tag])
    opposite_phrase = ", ".join(sorted(opposite_tags)) or "visually unrelated mismatched"
    views: dict[str, dict[str, Any]] = {}
    for axis, feature in view_features.items():
        image_path = Path(str(feature.get("image_path") or ""))
        if not image_path.is_file():
            continue
        semantic = semantic_scorer.score(image_path, semantic_form_contract)
        style = semantic_scorer.score_text_contrast(
            image_path,
            positive_prompts=[
                f"a product photo of one {identity} in a coherent {style_phrase} design",
                f"a complete {identity} whose shape, palette, and detail follow {style_phrase}",
            ],
            negative_prompts=[
                f"a product photo of one {identity} in a {opposite_phrase} style",
                f"a malformed object with an incoherent or unrelated design style",
            ],
            purpose="final_multiview_style_alignment",
        )
        views[axis] = {"semantic": semantic, "style_alignment": style}
    semantic_scores = [
        float(row["semantic"].get("score", 0.0))
        for row in views.values()
        if row["semantic"].get("evaluated")
    ]
    style_scores = [
        float(row["style_alignment"].get("score", 0.0))
        for row in views.values()
        if row["style_alignment"].get("evaluated")
    ]
    category_verified = bool(
        len(semantic_scores) == len(view_features) == 4
        and all(bool(row["semantic"].get("gate_passed")) for row in views.values())
    )
    mean_style = float(np.mean(style_scores)) if style_scores else 0.0
    minimum_style = min(style_scores, default=0.0)
    style_verified = bool(
        len(style_scores) == len(view_features) == 4
        and mean_style >= 0.50
        and minimum_style >= 0.40
    )
    return {
        "schema": "scene_dna_multiview_semantic_style_v1",
        "evaluated": bool(views) and len(views) == len(view_features),
        "model": getattr(semantic_scorer, "model_name_or_path", "custom_scorer"),
        "identity": identity,
        "desired_style_tags": style_tags,
        "views": views,
        "mean_semantic_score": round(float(np.mean(semantic_scores)), 6) if semantic_scores else None,
        "minimum_semantic_score": round(min(semantic_scores), 6) if semantic_scores else None,
        "semantic_category_verified": category_verified,
        "mean_style_alignment_score": round(mean_style, 6),
        "minimum_style_alignment_score": round(minimum_style, 6),
        "style_alignment_verified": style_verified,
        "style_gate": {"minimum_mean": 0.50, "minimum_worst_view": 0.40},
        "limitations": "zero-shot multi-view semantic/style evidence; thresholds remain experimental until blind-label calibration",
    }


def evaluate_multiview_manifest(
    manifest: dict[str, Any],
    contract: dict[str, Any],
    *,
    object_id: str,
    category: str,
    reference_image_path: Path | None = None,
    structure_profile: dict[str, Any] | None = None,
    semantic_scorer: Any | None = None,
) -> dict[str, Any]:
    view_paths = manifest.get("views", {}).get(object_id, {})
    desired_tags = _desired_tags(contract, object_id)
    individuality_tags = _individuality_tags(contract, object_id)
    features: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for axis in VIEW_AXES:
        path = Path(str(view_paths.get(axis) or ""))
        if not path.is_file():
            missing.append(axis)
            continue
        features[axis] = _image_features(
            path,
            desired_tags,
            priority_palette_tags=individuality_tags,
        )
    basic_structure_pass = len(features) == len(VIEW_AXES) and all(
        bool(item.get("ok")) for item in features.values()
    )
    structure_profile = deepcopy(structure_profile) if isinstance(structure_profile, dict) else {
        "profile": "general_object",
        "compact_silhouette_required": False,
        "minimum_bbox_fill": None,
        "maximum_detached_ratio": 0.08,
        "evidence": "profile_not_provided",
    }
    compact_silhouette_required = bool(
        structure_profile.get("compact_silhouette_required")
    )
    minimum_bbox_fill = float(
        structure_profile.get("minimum_bbox_fill", 0.0) or 0.0
    )
    maximum_detached_ratio = float(
        structure_profile.get("maximum_detached_ratio", 0.08) or 0.08
    )
    maximum_internal_hole_ratio = structure_profile.get(
        "maximum_internal_hole_ratio"
    )
    maximum_lower_overhang_ratio = structure_profile.get(
        "maximum_lower_overhang_ratio"
    )
    maximum_lower_full_width_row_fraction = structure_profile.get(
        "maximum_lower_full_width_row_fraction"
    )
    maximum_layered_footprint_ratio = structure_profile.get(
        "maximum_lower_to_upper_footprint_area_ratio"
    )
    compact_silhouette_pass = not compact_silhouette_required or all(
        float(item.get("bbox_fill_ratio", 0.0)) >= minimum_bbox_fill
        and float(item.get("detached_component_ratio", 1.0)) <= maximum_detached_ratio
        for item in features.values()
    )
    general_fragment_pass = all(
        float(item.get("detached_component_ratio", 1.0)) <= maximum_detached_ratio
        for item in features.values()
    ) if features else False
    internal_hole_pass = (
        maximum_internal_hole_ratio is None
        or all(
            float(item.get("internal_hole_ratio", 1.0))
            <= float(maximum_internal_hole_ratio)
            for item in features.values()
        )
    )
    lower_overhang_pass = (
        maximum_lower_overhang_ratio is None
        or all(
            float(item.get("lower_overhang_ratio", float("inf")))
            <= float(maximum_lower_overhang_ratio)
            for item in features.values()
        )
    )
    normalization = deepcopy(manifest.get("normalization", {}).get(object_id, {}))
    layered_footprint = normalization.get("layered_footprint")
    layered_footprint = layered_footprint if isinstance(layered_footprint, dict) else {}
    layered_ratio_evaluated = bool(layered_footprint.get("evaluated"))
    silhouette_platform_pass = (
        maximum_lower_full_width_row_fraction is None
        or all(
            float(item.get("lower_full_width_row_fraction", 1.0))
            <= float(maximum_lower_full_width_row_fraction)
            for item in features.values()
        )
    )
    if maximum_layered_footprint_ratio is not None and layered_ratio_evaluated:
        layered_platform_pass = bool(
            float(
                layered_footprint.get(
                    "lower_to_upper_footprint_area_ratio", float("inf")
                )
            )
            <= float(maximum_layered_footprint_ratio)
        )
        lower_platform_pass = bool(
            layered_platform_pass and silhouette_platform_pass
        )
        lower_platform_evidence = (
            "normalized_3d_layered_footprint+multiview_silhouette_row_occupancy"
        )
    else:
        lower_platform_pass = silhouette_platform_pass
        lower_platform_evidence = "multiview_silhouette_row_occupancy"
    silhouette_structure_pass = (
        basic_structure_pass
        and compact_silhouette_pass
        and general_fragment_pass
        and internal_hole_pass
        and lower_overhang_pass
        and lower_platform_pass
    )
    consistency = _opposite_view_consistency(features)
    style_scores = [float(item.get("style_score", 0.0)) for item in features.values()]
    mean_style = float(np.mean(style_scores)) if style_scores else 0.0
    minimum_style = min(style_scores, default=0.0)
    reference = _reference_appearance_score(reference_image_path, features)
    reference_score = float(reference.get("score", 0.5) or 0.5)
    semantic_form_contract = (
        contract.get("object_profiles", {})
        .get(object_id, {})
        .get("semantic_form_contract", {})
    )
    semantic_style = _semantic_style_multiview_score(
        features,
        semantic_scorer=semantic_scorer,
        semantic_form_contract=semantic_form_contract,
        desired_tags=desired_tags,
    )
    semantic_embedding_evaluated = bool(semantic_style.get("evaluated"))
    if semantic_embedding_evaluated:
        semantic_score = float(semantic_style.get("mean_semantic_score", 0.0) or 0.0)
        semantic_style_score = float(
            semantic_style.get("mean_style_alignment_score", 0.0) or 0.0
        )
        automated_score = (
            0.45 * mean_style
            + 0.20 * reference_score
            + 0.20 * semantic_style_score
            + 0.15 * semantic_score
        )
    else:
        automated_score = 0.75 * mean_style + 0.25 * reference_score
    threshold = float(contract.get("selection_policy", {}).get("minimum_harmony_score", 0.55))
    anisotropy = float(normalization.get("axis_scale_anisotropy", 1.0) or 1.0)
    scale_gate_passed = anisotropy <= 4.0
    hard_geometry_gate_passed = bool(
        silhouette_structure_pass
        and consistency["passes"]
        and scale_gate_passed
    )
    warnings: list[str] = []
    if anisotropy > 2.5:
        warnings.append("large_nonuniform_scale_required")
    if not bool(reference.get("evaluated")):
        warnings.append("selected_2d_reference_not_compared")
    passed = (
        hard_geometry_gate_passed
        and automated_score >= threshold
        and minimum_style >= max(0.0, threshold - 0.12)
        and (
            not semantic_embedding_evaluated
            or (
                bool(semantic_style.get("semantic_category_verified"))
                and bool(semantic_style.get("style_alignment_verified"))
            )
        )
    )
    return {
        "schema": "scene_dna_generated_asset_multiview_v1",
        "object_id": object_id,
        "category": category,
        "scene_dna_contract_hash": contract.get("contract_hash"),
        "evaluated": True,
        "rendered_view_count": len(features),
        "missing_views": missing,
        "desired_tags": sorted(desired_tags),
        "individuality_tags": sorted(individuality_tags),
        "views": features,
        "structure_gate_passed": silhouette_structure_pass,
        "hard_geometry_gate_passed": hard_geometry_gate_passed,
        "structure_gate": {
            "basic_foreground_passed": basic_structure_pass,
            "general_fragment_passed": general_fragment_pass,
            "profile": structure_profile,
            "compact_silhouette_required": compact_silhouette_required,
            "compact_silhouette_minimum_bbox_fill": (
                minimum_bbox_fill if compact_silhouette_required else None
            ),
            "compact_silhouette_maximum_detached_ratio": maximum_detached_ratio,
            "compact_silhouette_passed": compact_silhouette_pass,
            "maximum_internal_hole_ratio": maximum_internal_hole_ratio,
            "internal_hole_passed": internal_hole_pass,
            "maximum_lower_overhang_ratio": maximum_lower_overhang_ratio,
            "lower_overhang_passed": lower_overhang_pass,
            "maximum_lower_full_width_row_fraction": (
                maximum_lower_full_width_row_fraction
            ),
            "maximum_lower_to_upper_footprint_area_ratio": (
                maximum_layered_footprint_ratio
            ),
            "lower_to_upper_footprint_area_ratio": layered_footprint.get(
                "lower_to_upper_footprint_area_ratio"
            ),
            "lower_platform_evidence": lower_platform_evidence,
            "lower_platform_passed": lower_platform_pass,
        },
        "opposite_view_consistency": consistency,
        "normalization": normalization,
        "scale_anisotropy_gate": {
            "maximum": 4.0,
            "actual": round(anisotropy, 6),
            "passes": scale_gate_passed,
        },
        "reference_appearance": reference,
        "semantic_style_multiview": semantic_style,
        "mean_style_score": round(mean_style, 6),
        "minimum_view_style_score": round(minimum_style, 6),
        "automated_score": round(automated_score, 6),
        "threshold": threshold,
        "automated_pixel_multiview_pass": passed,
        "semantic_embedding_evaluated": semantic_embedding_evaluated,
        "semantic_category_verified": bool(
            semantic_style.get("semantic_category_verified")
        ),
        "semantic_style_verified": bool(
            semantic_style.get("style_alignment_verified")
        ),
        "warnings": warnings,
        "acceptance": (
            "automated_pixel_multiview_pass_semantic_review_required"
            if passed
            else "regenerate_or_style_review_required"
        ),
        "limitations": [
            "pixel silhouette and scale checks remain approximations of 3D topology",
            (
                "frozen multi-view semantic/style embedding included but still requires blind-label calibration"
                if semantic_embedding_evaluated
                else "semantic/style embedding scorer was not configured"
            ),
        ],
    }


def _write_contact_sheet(view_paths: dict[str, str], output_path: Path) -> None:
    thumb = 320
    label_height = 30
    canvas = Image.new("RGB", (thumb * 4, thumb + label_height), (228, 228, 228))
    draw = ImageDraw.Draw(canvas)
    for index, axis in enumerate(VIEW_AXES):
        path = Path(str(view_paths.get(axis) or ""))
        if path.is_file():
            with Image.open(path) as source:
                rgba = source.convert("RGBA")
                backdrop = Image.new("RGBA", rgba.size, (225, 225, 225, 255))
                backdrop.alpha_composite(rgba)
                image = backdrop.convert("RGB")
                image.thumbnail((thumb - 12, thumb - 12), Image.Resampling.LANCZOS)
                canvas.paste(image, (index * thumb + (thumb - image.width) // 2, 6))
        draw.text((index * thumb + 8, thumb + 7), f"view {axis}", fill=(20, 20, 20))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def render_and_evaluate_generated_asset(
    *,
    blender_bin: Path,
    asset_dir: Path,
    output_dir: Path,
    obj: dict[str, Any],
    contract: dict[str, Any],
    reference_image_path: Path | None = None,
    resolution: int = 420,
    semantic_scorer: Any | None = None,
    geometry_evidence: bool = False,
    evidence_resolution: int = 128,
) -> dict[str, Any]:
    object_id = str(obj["id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "scene_dna_multiview_plan.json"
    plan = {
        "schema": "scene_dna_multiview_render_plan_v1",
        "objects": [
            {
                "id": object_id,
                "category": str(obj.get("category") or ""),
                "dimensions": deepcopy(obj.get("dimensions")),
                "requested_dimensions": deepcopy(
                    obj.get("requested_dimensions") or obj.get("dimensions")
                ),
                "asset_axis_to_z": int(obj.get("asset_axis_to_z", 2)),
                "asset_axis_to_z_sign": float(obj.get("asset_axis_to_z_sign", 1.0) or 1.0),
                "asset_local_yaw_offset_degrees": float(
                    obj.get("asset_local_yaw_offset_degrees", 0.0) or 0.0
                ),
            }
        ],
    }
    plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    script = Path(__file__).resolve().parents[2] / "scripts" / "blender_render_asset_turntables.py"
    command = [
        str(blender_bin),
        "--background",
        "--python",
        str(script),
        "--",
        "--plan",
        str(plan_path),
        "--asset-dir",
        str(asset_dir),
        "--output-dir",
        str(output_dir),
        "--object-ids",
        object_id,
        "--resolution",
        str(int(resolution)),
        "--transparent",
        "--fit-requested-dimensions",
    ]
    if geometry_evidence:
        command.extend(
            [
                "--geometry-evidence",
                "--evidence-resolution",
                str(int(evidence_resolution)),
            ]
        )
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=900,
        check=False,
    )
    (output_dir / "blender_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "blender_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        return {
            "schema": "scene_dna_generated_asset_multiview_v1",
            "object_id": object_id,
            "category": str(obj.get("category") or ""),
            "scene_dna_contract_hash": contract.get("contract_hash"),
            "evaluated": False,
            "automated_pixel_multiview_pass": False,
            "acceptance": "render_failed_style_review_required",
            "error": completed.stderr[-2000:],
            "semantic_embedding_evaluated": False,
        }
    manifest_path = output_dir / "asset_turntable_manifest.json"
    if not manifest_path.is_file():
        return {
            "schema": "scene_dna_generated_asset_multiview_v1",
            "object_id": object_id,
            "category": str(obj.get("category") or ""),
            "scene_dna_contract_hash": contract.get("contract_hash"),
            "evaluated": False,
            "automated_pixel_multiview_pass": False,
            "acceptance": "manifest_missing_style_review_required",
            "semantic_embedding_evaluated": False,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    view_paths = manifest.get("views", {}).get(object_id, {})
    contact_sheet = output_dir / "scene_dna_multiview_contact_sheet.png"
    _write_contact_sheet(view_paths, contact_sheet)
    report = evaluate_multiview_manifest(
        manifest,
        contract,
        object_id=object_id,
        category=str(obj.get("category") or ""),
        reference_image_path=reference_image_path,
        structure_profile=structure_profile_for_object(
            obj,
            contract.get("object_profiles", {})
            .get(object_id, {})
            .get("semantic_form_contract", {}),
        ),
        semantic_scorer=semantic_scorer,
    )
    report["manifest_path"] = str(manifest_path)
    report["contact_sheet_path"] = str(contact_sheet)
    report_path = output_dir / "scene_dna_multiview_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
