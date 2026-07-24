from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Iterable

from .orientation import world_front_vector


EXECUTABLE_SPATIAL_RELATIONS = {
    "left_of",
    "right_of",
    "in_front_of",
    "separated_from",
    "clearance_from",
    "aligned_with",
    "mirror_symmetric",
}

RELATION_ALIASES = {
    "left": "left_of",
    "right": "right_of",
    "front_of": "in_front_of",
    "in_front": "in_front_of",
    "separate_from": "separated_from",
}

DEFAULT_MIN_GAPS = {
    "left_of": 0.04,
    "right_of": 0.04,
    "in_front_of": 0.12,
    "separated_from": 0.08,
    "clearance_from": 0.20,
    "aligned_with": 0.0,
    "mirror_symmetric": 0.0,
}

DEFAULT_MAX_GAPS = {
    "clearance_from": 0.90,
}

ANCHORS = {
    "center",
    "front_face",
    "back_face",
    "left_face",
    "right_face",
}

ALIGNMENT_AXES = {"depth", "left_right", "x", "y"}


def _number(
    value: Any, default: float, *, minimum: float = 0.0, maximum: float = 5.0
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result):
        result = default
    return min(maximum, max(minimum, result))


def _footprint(obj: dict[str, Any]) -> tuple[float, float]:
    dimensions = obj.get("dimensions") if isinstance(obj.get("dimensions"), dict) else {}
    width = float(dimensions.get("width", 0.0) or 0.0)
    length = float(dimensions.get("length", 0.0) or 0.0)
    quarter_turn = int(round(float(obj.get("yaw", 0.0) or 0.0) / 90.0)) % 2 == 1
    return (length, width) if quarter_turn else (width, length)


def _aabb(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    width, length = _footprint(obj)
    x = float(obj.get("x", 0.0) or 0.0)
    y = float(obj.get("y", 0.0) or 0.0)
    return x - width / 2.0, y - length / 2.0, x + width / 2.0, y + length / 2.0


def _projection_half_extent(obj: dict[str, Any], axis: tuple[float, float]) -> float:
    width, length = _footprint(obj)
    return abs(axis[0]) * width / 2.0 + abs(axis[1]) * length / 2.0


def _rectangle_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx0, ly0, lx1, ly1 = _aabb(left)
    rx0, ry0, rx1, ry1 = _aabb(right)
    dx = max(rx0 - lx1, lx0 - rx1, 0.0)
    dy = max(ry0 - ly1, ly0 - ry1, 0.0)
    return math.hypot(dx, dy)


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-9:
        return 0.0, -1.0
    return vector[0] / length, vector[1] / length


def _reference_axes(
    relation: dict[str, Any], target: dict[str, Any]
) -> tuple[tuple[float, float], tuple[float, float]]:
    frame = str(relation.get("reference_frame") or "target_local")
    if frame == "room":
        front = (0.0, -1.0)
        right = (1.0, 0.0)
        return front, right
    front = _unit(world_front_vector(target))
    right = (front[1], -front[0])
    return front, right


def _direction(
    relation: dict[str, Any], target: dict[str, Any]
) -> tuple[float, float]:
    front, right = _reference_axes(relation, target)
    relation_type = str(relation["type"])
    if relation_type == "left_of":
        return -right[0], -right[1]
    if relation_type == "right_of":
        return right
    return front


def _object_axes(
    obj: dict[str, Any],
) -> tuple[tuple[float, float], tuple[float, float]]:
    front = _unit(world_front_vector(obj))
    return front, (front[1], -front[0])


def _anchor_point(
    obj: dict[str, Any], anchor: str
) -> tuple[float, float]:
    center = (
        float(obj.get("x", 0.0) or 0.0),
        float(obj.get("y", 0.0) or 0.0),
    )
    front, right = _object_axes(obj)
    if anchor == "front_face":
        axis, sign = front, 1.0
    elif anchor == "back_face":
        axis, sign = front, -1.0
    elif anchor == "left_face":
        axis, sign = right, -1.0
    elif anchor == "right_face":
        axis, sign = right, 1.0
    else:
        return center
    extent = _projection_half_extent(obj, axis)
    return center[0] + sign * axis[0] * extent, center[1] + sign * axis[1] * extent


def _alignment_axis(
    relation: dict[str, Any], target: dict[str, Any]
) -> tuple[float, float]:
    axis_name = str(relation.get("alignment_axis") or "depth")
    if axis_name == "x":
        return 1.0, 0.0
    if axis_name == "y":
        return 0.0, 1.0
    front, right = _reference_axes(relation, target)
    return right if axis_name == "left_right" else front


def _mirror_point(
    point: tuple[float, float],
    reference: dict[str, Any],
    axis_name: str,
) -> tuple[float, float]:
    front, right = _object_axes(reference)
    delta = (
        point[0] - float(reference.get("x", 0.0) or 0.0),
        point[1] - float(reference.get("y", 0.0) or 0.0),
    )
    front_offset = delta[0] * front[0] + delta[1] * front[1]
    right_offset = delta[0] * right[0] + delta[1] * right[1]
    if axis_name == "front_back":
        front_offset = -front_offset
    else:
        right_offset = -right_offset
    return (
        float(reference.get("x", 0.0) or 0.0)
        + front[0] * front_offset
        + right[0] * right_offset,
        float(reference.get("y", 0.0) or 0.0)
        + front[1] * front_offset
        + right[1] * right_offset,
    )


def compile_spatial_relations(relations: Iterable[Any]) -> list[dict[str, Any]]:
    """Normalize executable 2D relation constraints and remove duplicate edges."""

    compiled: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in relations:
        structured = isinstance(raw, dict)
        if isinstance(raw, (list, tuple)) and len(raw) == 3:
            source, relation_type, target = (str(value) for value in raw)
            strength = "soft"
            parameters: dict[str, Any] = {}
            provenance = "legacy_relation"
        elif structured:
            source = str(raw.get("source") or raw.get("subject") or "")
            relation_type = str(raw.get("type") or raw.get("predicate") or "")
            target = str(raw.get("target") or raw.get("object") or "")
            strength = str(raw.get("strength") or "soft")
            parameters = (
                deepcopy(raw["parameters"])
                if isinstance(raw.get("parameters"), dict)
                else {}
            )
            provenance = str(raw.get("provenance") or "structured_relation")
        else:
            continue
        relation_type = RELATION_ALIASES.get(relation_type, relation_type)
        if relation_type not in EXECUTABLE_SPATIAL_RELATIONS or not source or not target:
            continue
        if source == target:
            continue
        strength = strength if strength in {"hard", "soft"} else "soft"
        default_frame = "room" if relation_type in {"left_of", "right_of"} else "target_local"
        reference_frame = str(
            parameters.get("reference_frame") or parameters.get("frame") or default_frame
        )
        if reference_frame not in {"room", "target_local"}:
            reference_frame = default_frame
        min_gap = _number(
            parameters.get("min_gap", parameters.get("minimum_distance")),
            DEFAULT_MIN_GAPS[relation_type],
            maximum=3.0,
        )
        raw_max_gap = parameters.get("max_gap", parameters.get("maximum_distance"))
        default_max = DEFAULT_MAX_GAPS.get(relation_type)
        max_gap = (
            _number(raw_max_gap, default_max or min_gap, minimum=min_gap, maximum=5.0)
            if raw_max_gap is not None or default_max is not None
            else None
        )
        raw_lateral = parameters.get(
            "lateral_tolerance", parameters.get("max_lateral_offset")
        )
        # Directional ordering does not imply center-line alignment. Preserve the
        # old behavior only when callers opt into it explicitly; aligned_with is
        # the general anchor-based alignment primitive.
        if relation_type in {"left_of", "right_of"} and str(
            parameters.get("alignment_mode") or ""
        ) != "center":
            raw_lateral = None
        lateral_tolerance = (
            _number(raw_lateral, 0.0, maximum=5.0)
            if raw_lateral is not None
            else None
        )
        tolerance = _number(parameters.get("position_tolerance"), 0.025, maximum=0.25)
        source_anchor = str(parameters.get("source_anchor") or "center")
        target_anchor = str(parameters.get("target_anchor") or "center")
        if source_anchor not in ANCHORS:
            source_anchor = "center"
        if target_anchor not in ANCHORS:
            target_anchor = "center"
        alignment_axis = str(parameters.get("axis") or "depth")
        if alignment_axis not in ALIGNMENT_AXES:
            alignment_axis = "depth"
        alignment_tolerance = _number(
            parameters.get("alignment_tolerance", parameters.get("position_tolerance")),
            0.08,
            maximum=0.5,
        )
        mirror_axis = str(parameters.get("axis") or "left_right")
        if mirror_axis not in {"left_right", "front_back"}:
            mirror_axis = "left_right"
        reference_id = str(
            parameters.get("reference_id")
            or parameters.get("about")
            or parameters.get("reference_object")
            or ""
        )
        side_role = str(parameters.get("side_role") or "")
        role_locked = parameters.get("role_locked") is True and side_role in {
            "left",
            "right",
        }
        role_reference_frame = str(
            parameters.get("role_reference_frame") or reference_frame
        )
        if role_reference_frame not in {"room", "target_local"}:
            role_reference_frame = reference_frame
        item = {
            "id": f"relation:{source}:{relation_type}:{target}",
            "source": source,
            "type": relation_type,
            "target": target,
            "strength": strength,
            "reference_frame": reference_frame,
            "min_gap": min_gap,
            "max_gap": max_gap,
            "lateral_tolerance": lateral_tolerance,
            "tolerance": tolerance,
            "source_anchor": source_anchor,
            "target_anchor": target_anchor,
            "alignment_axis": alignment_axis,
            "alignment_tolerance": alignment_tolerance,
            "mirror_axis": mirror_axis,
            "reference_id": reference_id,
            "side_role": side_role if side_role in {"left", "right"} else None,
            "role_locked": role_locked,
            "role_reference_frame": role_reference_frame,
            "role_source": str(parameters.get("role_source") or "") or None,
            "parameters": parameters,
            "provenance": provenance,
            "structured": structured,
        }
        key = source, relation_type, target
        previous = compiled.get(key)
        if previous is None or (
            item["strength"] == "hard" and previous["strength"] != "hard"
        ) or (item["structured"] and not previous["structured"]):
            compiled[key] = item
    return list(compiled.values())


def evaluate_spatial_relation(
    source: dict[str, Any],
    target: dict[str, Any],
    relation: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    relation_type = str(relation["type"])
    min_gap = float(relation["min_gap"])
    max_gap = relation.get("max_gap")
    max_gap = float(max_gap) if max_gap is not None else None
    tolerance = float(relation["tolerance"])
    lateral_offset: float | None = None

    alignment_error: float | None = None
    if relation_type == "aligned_with":
        axis = _unit(_alignment_axis(relation, target))
        source_anchor = _anchor_point(source, str(relation["source_anchor"]))
        target_anchor = _anchor_point(target, str(relation["target_anchor"]))
        alignment_error = abs(
            (source_anchor[0] - target_anchor[0]) * axis[0]
            + (source_anchor[1] - target_anchor[1]) * axis[1]
        )
        gap = alignment_error
    elif relation_type == "mirror_symmetric":
        reference = (objects_by_id or {}).get(str(relation.get("reference_id") or ""))
        if reference is None:
            gap = 5.0
            alignment_error = 5.0
        else:
            expected = _mirror_point(
                (float(target.get("x", 0.0)), float(target.get("y", 0.0))),
                reference,
                str(relation.get("mirror_axis") or "left_right"),
            )
            alignment_error = math.hypot(
                float(source.get("x", 0.0)) - expected[0],
                float(source.get("y", 0.0)) - expected[1],
            )
            gap = alignment_error
    elif relation_type in {"left_of", "right_of", "in_front_of"}:
        direction = _direction(relation, target)
        transverse = (-direction[1], direction[0])
        delta = (
            float(source.get("x", 0.0)) - float(target.get("x", 0.0)),
            float(source.get("y", 0.0)) - float(target.get("y", 0.0)),
        )
        center_projection = delta[0] * direction[0] + delta[1] * direction[1]
        gap = center_projection - _projection_half_extent(
            source, direction
        ) - _projection_half_extent(target, direction)
        lateral_offset = abs(delta[0] * transverse[0] + delta[1] * transverse[1])
    else:
        gap = _rectangle_distance(source, target)

    if relation_type in {"aligned_with", "mirror_symmetric"}:
        minimum_residual = 0.0
        maximum_residual = max(
            0.0, float(alignment_error or 0.0) - float(relation["alignment_tolerance"])
        )
    else:
        minimum_residual = max(0.0, min_gap - gap - tolerance)
        maximum_residual = (
            max(0.0, gap - max_gap - tolerance) if max_gap is not None else 0.0
        )
    lateral_tolerance = relation.get("lateral_tolerance")
    lateral_residual = (
        max(0.0, float(lateral_offset or 0.0) - float(lateral_tolerance) - tolerance)
        if lateral_tolerance is not None
        else 0.0
    )
    constraint_residual = minimum_residual + maximum_residual + lateral_residual
    relation_ok = constraint_residual <= 1e-9
    role_assignment_gap: float | None = None
    role_assignment_residual = 0.0
    role_assignment_ok: bool | None = None
    if relation.get("role_locked") and relation.get("side_role") in {"left", "right"}:
        role_relation = {
            **relation,
            "type": f"{relation['side_role']}_of",
            "reference_frame": relation["role_reference_frame"],
        }
        role_direction = _direction(role_relation, target)
        role_delta = (
            float(source.get("x", 0.0)) - float(target.get("x", 0.0)),
            float(source.get("y", 0.0)) - float(target.get("y", 0.0)),
        )
        role_assignment_gap = (
            role_delta[0] * role_direction[0]
            + role_delta[1] * role_direction[1]
            - _projection_half_extent(source, role_direction)
            - _projection_half_extent(target, role_direction)
        )
        role_assignment_residual = max(
            0.0, min_gap - role_assignment_gap - tolerance
        )
        role_assignment_ok = role_assignment_residual <= 1e-9
    residual = max(constraint_residual, role_assignment_residual)
    effective_strength = (
        "hard"
        if role_assignment_ok is False and relation.get("role_locked")
        else relation["strength"]
    )
    return {
        "relation_id": relation["id"],
        "type": relation_type,
        "source": relation["source"],
        "target": relation["target"],
        "strength": effective_strength,
        "relation_strength": relation["strength"],
        "reference_frame": relation["reference_frame"],
        "gap": round(gap, 6),
        "min_gap": min_gap,
        "max_gap": max_gap,
        "lateral_offset": round(lateral_offset, 6) if lateral_offset is not None else None,
        "lateral_tolerance": lateral_tolerance,
        "source_anchor": relation.get("source_anchor") if relation_type == "aligned_with" else None,
        "target_anchor": relation.get("target_anchor") if relation_type == "aligned_with" else None,
        "alignment_axis": relation.get("alignment_axis") if relation_type == "aligned_with" else None,
        "alignment_error": round(alignment_error, 6) if alignment_error is not None else None,
        "alignment_tolerance": relation.get("alignment_tolerance") if relation_type in {"aligned_with", "mirror_symmetric"} else None,
        "reference_id": relation.get("reference_id") if relation_type == "mirror_symmetric" else None,
        "mirror_axis": relation.get("mirror_axis") if relation_type == "mirror_symmetric" else None,
        "constraint_residual": round(constraint_residual, 6),
        "relation_ok": relation_ok,
        "side_role": relation.get("side_role"),
        "role_locked": bool(relation.get("role_locked")),
        "role_reference_frame": relation.get("role_reference_frame"),
        "role_source": relation.get("role_source"),
        "role_assignment_gap": (
            round(role_assignment_gap, 6)
            if role_assignment_gap is not None
            else None
        ),
        "role_assignment_residual": round(role_assignment_residual, 6),
        "role_assignment_ok": role_assignment_ok,
        "residual": round(residual, 6),
        "ok": relation_ok and role_assignment_ok is not False,
        "provenance": relation["provenance"],
    }


def evaluate_spatial_relations(
    objects: Iterable[dict[str, Any]], relations: Iterable[Any]
) -> list[dict[str, Any]]:
    by_id = {
        str(obj["id"]): obj
        for obj in objects
        if isinstance(obj, dict) and obj.get("id")
    }
    statuses: list[dict[str, Any]] = []
    for relation in compile_spatial_relations(relations):
        source = by_id.get(str(relation["source"]))
        target = by_id.get(str(relation["target"]))
        if source is None or target is None:
            continue
        statuses.append(evaluate_spatial_relation(source, target, relation, by_id))
    return statuses


def spatial_relation_rank(statuses: Iterable[dict[str, Any]]) -> tuple[int, float, int, float]:
    rows = list(statuses)
    hard = [row for row in rows if row["strength"] == "hard" and not row["ok"]]
    soft = [row for row in rows if row["strength"] == "soft" and not row["ok"]]
    return (
        len(hard),
        round(sum(float(row["residual"]) for row in hard), 6),
        len(soft),
        round(sum(float(row["residual"]) for row in soft), 6),
    )


def relation_candidate_positions(
    source: dict[str, Any],
    target: dict[str, Any],
    relation: dict[str, Any],
    objects_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[tuple[float, float]]:
    """Generate exact target-relative seeds in addition to the room grid."""

    relation_type = str(relation["type"])
    if relation_type == "aligned_with":
        axis = _unit(_alignment_axis(relation, target))
        source_anchor = _anchor_point(source, str(relation["source_anchor"]))
        target_anchor = _anchor_point(target, str(relation["target_anchor"]))
        signed_error = (
            (source_anchor[0] - target_anchor[0]) * axis[0]
            + (source_anchor[1] - target_anchor[1]) * axis[1]
        )
        return [
            (
                float(source.get("x", 0.0)) - axis[0] * signed_error,
                float(source.get("y", 0.0)) - axis[1] * signed_error,
            )
        ]
    if relation_type == "mirror_symmetric":
        reference = (objects_by_id or {}).get(str(relation.get("reference_id") or ""))
        if reference is None:
            return []
        return [
            _mirror_point(
                (float(target.get("x", 0.0)), float(target.get("y", 0.0))),
                reference,
                str(relation.get("mirror_axis") or "left_right"),
            )
        ]

    tolerance = float(relation["tolerance"])
    gaps = [float(relation["min_gap"]) + tolerance]
    max_gap = relation.get("max_gap")
    if max_gap is not None and float(max_gap) > gaps[0] + tolerance:
        gaps.append((float(relation["min_gap"]) + float(max_gap)) / 2.0)

    if relation_type in {"left_of", "right_of", "in_front_of"}:
        directions = [_direction(relation, target)]
    else:
        front, right = _reference_axes(relation, target)
        current_delta = (
            float(source.get("x", 0.0)) - float(target.get("x", 0.0)),
            float(source.get("y", 0.0)) - float(target.get("y", 0.0)),
        )
        directions = [
            _unit(current_delta),
            front,
            (-front[0], -front[1]),
            right,
            (-right[0], -right[1]),
        ]

    result: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for direction in directions:
        direction = _unit(direction)
        transverse = (-direction[1], direction[0])
        lateral_tolerance = relation.get("lateral_tolerance")
        current_delta = (
            float(source.get("x", 0.0)) - float(target.get("x", 0.0)),
            float(source.get("y", 0.0)) - float(target.get("y", 0.0)),
        )
        current_lateral = (
            current_delta[0] * transverse[0] + current_delta[1] * transverse[1]
        )
        lateral_offsets = [current_lateral, 0.0]
        if lateral_tolerance is not None and float(lateral_tolerance) > 0.1:
            lateral_offsets.extend(
                [-float(lateral_tolerance) / 2.0, float(lateral_tolerance) / 2.0]
            )
        for gap in gaps:
            center_distance = (
                _projection_half_extent(source, direction)
                + _projection_half_extent(target, direction)
                + gap
            )
            for lateral in lateral_offsets:
                position = (
                    float(target.get("x", 0.0))
                    + direction[0] * center_distance
                    + transverse[0] * lateral,
                    float(target.get("y", 0.0))
                    + direction[1] * center_distance
                    + transverse[1] * lateral,
                )
                key = round(position[0], 6), round(position[1], 6)
                if key in seen:
                    continue
                seen.add(key)
                result.append(position)
    return result
