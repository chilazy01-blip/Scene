from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .io_utils import read_json, write_json


def _image_array(path: Path, mode: str) -> np.ndarray | None:
    if not path.is_file():
        return None
    with Image.open(path) as image:
        return np.asarray(image.convert(mode))


def evaluate_scene_render_manifest(
    manifest: dict[str, Any],
    plan: dict[str, Any],
    *,
    minimum_visible_pixels: int = 16,
    minimum_bbox_visibility_ratio: float = 0.015,
) -> dict[str, Any]:
    """Audit real RGB/depth/instance masks after scene assembly.

    The ratio is intentionally called a bbox visibility proxy: a projected box
    overestimates a real silhouette, but unlike the pre-layout proxy its
    numerator is measured from the final occluded render.
    """

    qa = manifest.get("qa_passes")
    qa = qa if isinstance(qa, dict) else {}
    views = qa.get("views")
    views = views if isinstance(views, dict) else {}
    required_ids = {
        str(obj.get("id"))
        for obj in plan.get("objects", [])
        if isinstance(obj, dict)
        and obj.get("id")
        and bool(obj.get("required", True))
    }
    view_reports: dict[str, dict[str, Any]] = {}
    object_observations: dict[str, list[dict[str, Any]]] = {
        object_id: [] for object_id in required_ids
    }
    hard_failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for view_name, row in views.items():
        if not isinstance(row, dict):
            continue
        rgb_path = Path(str(row.get("rgb_path") or ""))
        depth_path = Path(str(row.get("depth_path") or ""))
        rgb = _image_array(rgb_path, "RGB")
        depth = _image_array(depth_path, "I")
        rgb_ok = rgb is not None and rgb.size > 0
        depth_ok = depth is not None and depth.size > 0 and int(depth.max()) > int(depth.min())
        if not rgb_ok:
            hard_failures.append({"type": "missing_or_invalid_rgb", "view": view_name})
        if not depth_ok:
            hard_failures.append({"type": "missing_or_flat_depth", "view": view_name})
        object_reports: dict[str, dict[str, Any]] = {}
        for object_id, object_row in (row.get("objects") or {}).items():
            if not isinstance(object_row, dict):
                continue
            mask_path = Path(str(object_row.get("mask_path") or ""))
            index_path = Path(str(object_row.get("object_index_path") or row.get("object_index_path") or ""))
            if mask_path.is_file():
                mask_array = _image_array(mask_path, "L")
                mask = mask_array > 127 if mask_array is not None else None
            else:
                index_array = _image_array(index_path, "I")
                denominator = int(
                    object_row.get("object_index_denominator")
                    or row.get("object_index_denominator")
                    or 1
                )
                pass_index = int(object_row.get("pass_index", 0) or 0)
                if index_array is not None:
                    maximum_pixel_value = float(
                        object_row.get("object_index_max_pixel_value")
                        or row.get("object_index_max_pixel_value")
                        or 65535
                    )
                    normalized = (
                        index_array.astype(np.float64)
                        / max(1.0, maximum_pixel_value)
                    )
                    transfer = str(
                        object_row.get("object_index_transfer")
                        or row.get("object_index_transfer")
                        or "linear"
                    )
                    if transfer == "srgb_from_linear":
                        normalized = np.where(
                            normalized <= 0.04045,
                            normalized / 12.92,
                            np.power((normalized + 0.055) / 1.055, 2.4),
                        )
                    decoded_indices = np.rint(
                        normalized * float(max(1, denominator))
                    ).astype(np.int32)
                    mask = decoded_indices == pass_index
                else:
                    mask = None
            visible_pixels = int(np.count_nonzero(mask)) if mask is not None else 0
            if mask is not None and visible_pixels:
                ys, xs = np.nonzero(mask)
                bbox = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                touches_border = bool(
                    xs.min() == 0
                    or ys.min() == 0
                    or xs.max() == mask.shape[1] - 1
                    or ys.max() == mask.shape[0] - 1
                )
            else:
                bbox = None
                touches_border = False
            projection = object_row.get("projection")
            projection = projection if isinstance(projection, dict) else {}
            projected_area = int(projection.get("projected_bbox_area_pixels", 0) or 0)
            visibility_ratio = visible_pixels / float(max(1, projected_area))
            observation = {
                "view": str(view_name),
                "mask_path": str(mask_path),
                "object_index_path": str(index_path),
                "mask_decoded": mask is not None,
                "visible_pixels": visible_pixels,
                "visible_bbox_pixels": bbox,
                "touches_image_border": touches_border,
                "projected_bbox_area_pixels": projected_area,
                "bbox_visibility_ratio_proxy": round(visibility_ratio, 6),
                "matched_mesh_count": int(projection.get("matched_mesh_count", 0) or 0),
                "projection_inside_frame": bool(projection.get("bbox_inside_frame")),
            }
            object_reports[str(object_id)] = observation
            if str(object_id) in object_observations:
                object_observations[str(object_id)].append(observation)
        view_reports[str(view_name)] = {
            "rgb_path": str(rgb_path),
            "rgb_ok": rgb_ok,
            "depth_path": str(depth_path),
            "depth_ok": depth_ok,
            "depth_dynamic_range": (
                int(depth.max()) - int(depth.min()) if depth is not None else None
            ),
            "objects": object_reports,
        }

    object_reports: dict[str, dict[str, Any]] = {}
    for object_id in sorted(required_ids):
        observations = object_observations.get(object_id, [])
        matched = any(item["matched_mesh_count"] > 0 for item in observations)
        visible = [
            item
            for item in observations
            if item["visible_pixels"] >= int(minimum_visible_pixels)
            and item["bbox_visibility_ratio_proxy"] >= float(minimum_bbox_visibility_ratio)
        ]
        complete_views = [
            item
            for item in visible
            if not item["touches_image_border"] and item["projection_inside_frame"]
        ]
        best = max(
            observations,
            key=lambda item: (
                float(item["bbox_visibility_ratio_proxy"]),
                int(item["visible_pixels"]),
            ),
            default=None,
        )
        if not matched:
            hard_failures.append({"type": "required_object_mesh_not_matched", "object_id": object_id})
        elif not visible:
            hard_failures.append({"type": "required_object_not_visibly_rendered", "object_id": object_id})
        elif not complete_views:
            warnings.append({"type": "required_object_never_complete_in_frame", "object_id": object_id})
        object_reports[object_id] = {
            "matched": matched,
            "visible_in_any_view": bool(visible),
            "complete_in_any_view": bool(complete_views),
            "best_observation": deepcopy(best),
            "observations": observations,
        }

    complete_visibility_required = bool(
        plan.get("camera_requirements", {}).get(
            "complete_required_objects_visible", False
        )
    )
    if complete_visibility_required:
        for object_id, report in object_reports.items():
            if report["visible_in_any_view"] and not report["complete_in_any_view"]:
                hard_failures.append(
                    {"type": "complete_visibility_requirement_failed", "object_id": object_id}
                )
    return {
        "schema": "scene_render_rgb_depth_instance_acceptance_v1",
        "evaluated": bool(views),
        "accepted": bool(views) and not hard_failures,
        "required_object_count": len(required_ids),
        "visible_required_object_count": sum(
            bool(row["visible_in_any_view"]) for row in object_reports.values()
        ),
        "complete_required_object_count": sum(
            bool(row["complete_in_any_view"]) for row in object_reports.values()
        ),
        "complete_visibility_required": complete_visibility_required,
        "thresholds": {
            "minimum_visible_pixels": int(minimum_visible_pixels),
            "minimum_bbox_visibility_ratio_proxy": float(minimum_bbox_visibility_ratio),
        },
        "views": view_reports,
        "objects": object_reports,
        "hard_failures": hard_failures,
        "warnings": warnings,
        "limitations": [
            "projected bounding-box area overestimates the true isolated silhouette",
            "instance masks measure final visible pixels and therefore include real occlusion",
        ],
    }


def render_and_evaluate_scene(
    *,
    blender_bin: Path,
    scene_glb: Path,
    plan_path: Path,
    asset_dir: Path,
    output_dir: Path,
    resolution: int = 512,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parents[2] / "scripts" / "blender_render_sage_diagnostics.py"
    command = [
        str(blender_bin),
        "--background",
        "--python",
        str(script),
        "--",
        "--scene-glb",
        str(scene_glb),
        "--plan",
        str(plan_path),
        "--asset-dir",
        str(asset_dir),
        "--output-dir",
        str(output_dir),
        "--resolution",
        str(int(resolution)),
        "--skip-assets",
        "--qa-passes",
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=1800,
        check=False,
    )
    (output_dir / "blender_stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "blender_stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        report = {
            "schema": "scene_render_rgb_depth_instance_acceptance_v1",
            "evaluated": False,
            "accepted": False,
            "hard_failures": [
                {
                    "type": "blender_render_failed",
                    "returncode": completed.returncode,
                    "error": completed.stderr[-4000:],
                }
            ],
        }
    else:
        manifest = read_json(output_dir / "render_manifest.json")
        plan = read_json(plan_path)
        report = evaluate_scene_render_manifest(manifest, plan)
        report["render_manifest_path"] = str(output_dir / "render_manifest.json")
    write_json(output_dir / "scene_render_acceptance_report.json", report)
    return report
