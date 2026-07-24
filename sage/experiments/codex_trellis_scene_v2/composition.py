from __future__ import annotations

from typing import Any


def camera_requirements_from_prompt(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    strict_front = any(
        phrase in lowered
        for phrase in ("strict front-facing", "strictly front-facing", "严格正面", "正视图")
    )
    eye_level = "eye-level" in lowered or "eye level" in lowered or "视平线" in lowered
    centered = "centered composition" in lowered or "居中构图" in lowered
    reduced_perspective = any(
        phrase in lowered
        for phrase in ("reduced perspective", "minimal perspective", "低透视", "减少透视")
    )
    complete_visibility = any(
        phrase in lowered
        for phrase in ("complete visible shapes", "fully visible", "完整可见", "完整形状")
    )
    minimal_occlusion = "minimal occlusion" in lowered or "少遮挡" in lowered or "最小遮挡" in lowered
    return {
        "schema": "codex_trellis_camera_requirements_v1",
        "view_axis": "south_to_north",
        "strict_front_facing": strict_front,
        "eye_level": eye_level,
        "eye_height": 1.55,
        "centered_composition": centered,
        "reduced_perspective": reduced_perspective,
        "focal_length_mm": 65.0 if reduced_perspective else 50.0,
        "sensor_width_mm": 36.0,
        "aspect_ratio": 4.0 / 3.0,
        "complete_required_objects_visible": complete_visibility,
        "minimal_occlusion": minimal_occlusion,
        "constraints_explicit": any(
            (strict_front, eye_level, centered, reduced_perspective, complete_visibility, minimal_occlusion)
        ),
    }


def render_requirements_from_prompt(prompt: str) -> dict[str, Any]:
    lowered = prompt.lower()
    return {
        "lighting": "bright_uniform_diffuse"
        if any(phrase in lowered for phrase in ("bright diffuse", "uniform bright", "明亮漫射"))
        else "neutral_diffuse",
        "stable_exposure": "stable exposure" in lowered or "稳定曝光" in lowered,
        "dramatic_shadows_allowed": not (
            "no dramatic shadows" in lowered or "无戏剧性阴影" in lowered
        ),
        "dataset_style": any(
            phrase in lowered
            for phrase in ("rgb-d dataset", "reconstruction dataset", "重建数据集")
        ),
        "depth_friendly": "depth-estimation friendly" in lowered or "深度估计友好" in lowered,
        "segmentation_friendly": (
            "semantic-segmentation friendly" in lowered or "语义分割友好" in lowered
        ),
    }


def _footprint(obj: dict[str, Any]) -> tuple[float, float]:
    dims = obj["dimensions"]
    width = float(dims["width"])
    length = float(dims["length"])
    quarter_turn = int(round(float(obj.get("yaw", 0.0)) / 90.0)) % 2 == 1
    return (length, width) if quarter_turn else (width, length)


def _projected_box(
    obj: dict[str, Any], camera: dict[str, Any], room: dict[str, Any]
) -> tuple[float, float, float, float, float]:
    width, length = _footprint(obj)
    x = float(obj.get("x", 0.0))
    y = float(obj.get("y", 0.0))
    z0 = float(obj.get("z", 0.0))
    z1 = z0 + float(obj["dimensions"]["height"])
    focal = float(camera["focal_length_mm"])
    sensor_width = float(camera["sensor_width_mm"])
    sensor_height = sensor_width / float(camera["aspect_ratio"])
    eye_height = float(camera["eye_height"])
    room_width = float(room["width"])
    camera_distance = max(5.0, room_width * focal / (sensor_width * 0.88))
    samples: list[tuple[float, float]] = []
    depths: list[float] = []
    for corner_x in (x - width / 2.0, x + width / 2.0):
        for corner_y in (y - length / 2.0, y + length / 2.0):
            depth = max(0.05, camera_distance + corner_y)
            depths.append(depth)
            for corner_z in (z0, z1):
                u = 0.5 + focal * (corner_x - room_width / 2.0) / (sensor_width * depth)
                v = 0.5 - focal * (corner_z - eye_height) / (sensor_height * depth)
                samples.append((u, v))
    return (
        min(item[0] for item in samples),
        min(item[1] for item in samples),
        max(item[0] for item in samples),
        max(item[1] for item in samples),
        sum(depths) / len(depths),
    )


def _area(box: tuple[float, float, float, float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection_area(
    left: tuple[float, float, float, float], right: tuple[float, float, float, float]
) -> float:
    return max(0.0, min(left[2], right[2]) - max(left[0], right[0])) * max(
        0.0, min(left[3], right[3]) - max(left[1], right[1])
    )


def _centeredness(plan: dict[str, Any]) -> float:
    primary_ids = {
        "bedroom": ("bed",),
        "living_room": ("sofa", "coffee_table"),
        "kitchen": ("dining_table",),
        "study": ("desk",),
        "restroom": ("vanity_sink",),
    }.get(str(plan.get("room_type")), ())
    primaries = [obj for obj in plan.get("objects", []) if obj.get("id") in primary_ids]
    if not primaries:
        return 1.0
    group_x = sum(float(obj.get("x", 0.0)) for obj in primaries) / len(primaries)
    half_width = max(0.001, float(plan["room"]["width"]) / 2.0)
    return max(0.0, 1.0 - abs(group_x - half_width) / (half_width * 0.5))


def _bedroom_symmetry(plan: dict[str, Any]) -> float:
    by_id = {str(obj.get("id")): obj for obj in plan.get("objects", [])}
    bed = by_id.get("bed")
    left = by_id.get("nightstand_left")
    right = by_id.get("nightstand_right")
    if not bed or not left or not right:
        return 1.0
    left_gap = abs(float(bed["x"]) - float(left["x"]))
    right_gap = abs(float(right["x"]) - float(bed["x"]))
    scale = max(0.25, (left_gap + right_gap) / 2.0)
    return max(0.0, 1.0 - abs(left_gap - right_gap) / scale)


def evaluate_composition(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    camera = plan.get("camera_requirements")
    if not isinstance(camera, dict):
        camera = camera_requirements_from_prompt(str(plan.get("description", "")))
    projected: dict[str, tuple[float, float, float, float, float]] = {}
    objects = [obj for obj in plan.get("objects", []) if isinstance(obj, dict)]
    for obj in objects:
        projected[str(obj.get("id"))] = _projected_box(obj, camera, plan["room"])

    framing_by_id: dict[str, float] = {}
    clarity_by_id: dict[str, float] = {}
    for obj in objects:
        object_id = str(obj.get("id"))
        raw = projected[object_id]
        box = raw[:4]
        box_area = max(1e-9, _area(box))
        clipped = (
            max(0.0, box[0]),
            max(0.0, box[1]),
            min(1.0, box[2]),
            min(1.0, box[3]),
        )
        framing_by_id[object_id] = max(0.0, min(1.0, _area(clipped) / box_area))
        occlusion = 0.0
        for other in objects:
            other_id = str(other.get("id"))
            if other_id == object_id or projected[other_id][4] >= raw[4] - 0.02:
                continue
            occlusion = max(
                occlusion,
                _intersection_area(box, projected[other_id][:4]) / box_area,
            )
        clarity_by_id[object_id] = max(0.0, 1.0 - min(1.0, occlusion))

    required_ids = {
        str(item)
        for item in plan.get("object_budget", {}).get("required_object_ids", [])
    }
    scored_ids = required_ids & set(projected) or set(projected)
    framing_score = sum(framing_by_id[item] for item in scored_ids) / max(1, len(scored_ids))
    clarity_score = sum(clarity_by_id[item] for item in scored_ids) / max(1, len(scored_ids))
    centeredness = _centeredness(plan)
    symmetry = _bedroom_symmetry(plan) if plan.get("room_type") == "bedroom" else 1.0
    score = 0.35 * framing_score + 0.30 * clarity_score + 0.25 * centeredness + 0.10 * symmetry

    violations: list[dict[str, Any]] = []
    clipped_required = sorted(item for item in required_ids if framing_by_id.get(item, 1.0) < 0.98)
    occluded_required = sorted(item for item in required_ids if clarity_by_id.get(item, 1.0) < 0.70)
    if camera.get("complete_required_objects_visible") and clipped_required:
        violations.append(
            {"type": "composition_required_object_clipped", "severity": "hard", "object_ids": clipped_required}
        )
    if camera.get("minimal_occlusion") and occluded_required:
        violations.append(
            {
                "type": "composition_required_object_occluded",
                "severity": "hard" if clarity_score < 0.50 else "soft",
                "object_ids": occluded_required,
                "clarity_score": round(clarity_score, 4),
            }
        )
    if camera.get("centered_composition") and centeredness < 0.72:
        violations.append(
            {
                "type": "composition_primary_group_off_center",
                "severity": "hard",
                "centeredness_score": round(centeredness, 4),
            }
        )
    elif centeredness < 0.55:
        violations.append(
            {
                "type": "composition_primary_group_off_center",
                "severity": "soft",
                "centeredness_score": round(centeredness, 4),
            }
        )

    return violations, {
        "evaluation_domain": "layout_camera_projection_proxy",
        "score": round(max(0.0, min(1.0, score)), 4),
        "framing_score": round(framing_score, 4),
        "clarity_score": round(clarity_score, 4),
        "centeredness_score": round(centeredness, 4),
        "symmetry_score": round(symmetry, 4),
        "camera_requirements": camera,
        "clipped_required_object_ids": clipped_required,
        "occluded_required_object_ids": occluded_required,
        "note": "Pre-render proxy from planned boxes; final RGB/depth/mask scoring remains a render-stage gate.",
    }
