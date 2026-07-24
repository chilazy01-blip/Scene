from __future__ import annotations

import math
from typing import Any, Iterable


AXIS_VECTORS: dict[str, tuple[float, float]] = {
    "+x": (1.0, 0.0),
    "x": (1.0, 0.0),
    "-x": (-1.0, 0.0),
    "+y": (0.0, 1.0),
    "y": (0.0, 1.0),
    "-y": (0.0, -1.0),
}

WALL_INWARD_NORMALS: dict[str, tuple[float, float]] = {
    "north": (0.0, -1.0),
    "south": (0.0, 1.0),
    "east": (-1.0, 0.0),
    "west": (1.0, 0.0),
}

CARDINAL_YAWS = (0.0, 90.0, 180.0, 270.0)


def _rotate(vector: tuple[float, float], degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
    )


def _angle_error(
    actual: tuple[float, float], expected: tuple[float, float]
) -> float:
    dot = max(-1.0, min(1.0, actual[0] * expected[0] + actual[1] * expected[1]))
    return math.degrees(math.acos(dot))


def _circular_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def facing_constraint(obj: dict[str, Any]) -> dict[str, Any] | None:
    raw = obj.get("facing_constraint")
    if not isinstance(raw, dict) or str(raw.get("mode")) != "into_room":
        return None
    wall = str(raw.get("wall") or obj.get("preferred_wall") or "")
    if wall not in WALL_INWARD_NORMALS:
        return None
    result = dict(raw)
    result["wall"] = wall
    return result


def canonical_front(obj: dict[str, Any]) -> dict[str, Any]:
    legacy = obj.get("asset_canonical_front")
    if isinstance(legacy, dict) and str(legacy.get("axis", "")).lower() in AXIS_VECTORS:
        return {
            "axis": str(legacy["axis"]).lower(),
            "confidence": float(legacy.get("confidence", 0.0) or 0.0),
            "source": "asset_canonical_front",
        }
    orientation = obj.get("asset_orientation")
    if isinstance(orientation, dict):
        axis = str(orientation.get("canonical_front_axis") or "").lower()
        if axis in AXIS_VECTORS:
            return {
                "axis": axis,
                "confidence": float(orientation.get("confidence", 0.0) or 0.0),
                "source": "asset_orientation",
            }
    constraint = facing_constraint(obj) or {}
    fallback = str(constraint.get("local_front_fallback") or "-y").lower()
    return {
        "axis": fallback if fallback in AXIS_VECTORS else "-y",
        "confidence": 0.0,
        "source": "policy_fallback",
    }


def world_front_vector(
    obj: dict[str, Any], *, yaw: float | None = None
) -> tuple[float, float]:
    front = canonical_front(obj)
    vector = AXIS_VECTORS[str(front["axis"])]
    rotation = (
        float(obj.get("yaw", 0.0) if yaw is None else yaw)
        + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
        + float(obj.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
    )
    return _rotate(vector, rotation)


def evaluate_facing(obj: dict[str, Any]) -> dict[str, Any] | None:
    constraint = facing_constraint(obj)
    if not constraint:
        return None
    wall = str(constraint["wall"])
    expected = WALL_INWARD_NORMALS[wall]
    actual = world_front_vector(obj)
    front = canonical_front(obj)
    tolerance = float(constraint.get("tolerance_degrees", 15.0) or 15.0)
    error = _angle_error(actual, expected)
    return {
        "object_id": str(obj.get("id") or ""),
        "mode": "into_room",
        "wall": wall,
        "contact_face": str(constraint.get("contact_face") or "back"),
        "canonical_front_axis": front["axis"],
        "canonical_front_source": front["source"],
        "canonical_front_confidence": float(front["confidence"]),
        "world_front": [round(actual[0], 6), round(actual[1], 6)],
        "expected_front": [expected[0], expected[1]],
        "angle_error_degrees": round(error, 6),
        "tolerance_degrees": tolerance,
        "ok": error <= tolerance + 1e-6,
    }


def solve_facing_yaw(
    obj: dict[str, Any], candidates: Iterable[float] = CARDINAL_YAWS
) -> float | None:
    constraint = facing_constraint(obj)
    if not constraint:
        return None
    expected = WALL_INWARD_NORMALS[str(constraint["wall"])]
    current = float(obj.get("yaw", 0.0) or 0.0) % 360.0
    ranked = [
        (
            _angle_error(world_front_vector(obj, yaw=float(candidate)), expected),
            _circular_difference(float(candidate), current),
            float(candidate) % 360.0,
        )
        for candidate in candidates
    ]
    return min(ranked)[2]


def apply_facing_constraints(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for obj in objects:
        solved = solve_facing_yaw(obj)
        if solved is None:
            continue
        previous = float(obj.get("yaw", 0.0) or 0.0) % 360.0
        obj["yaw"] = solved
        status = evaluate_facing(obj)
        if status:
            obj["facing_resolution"] = status
        if _circular_difference(previous, solved) > 1e-6:
            changes.append(
                {
                    "object_id": str(obj.get("id") or ""),
                    "from_yaw": previous,
                    "to_yaw": solved,
                    "reason": "functional_front_toward_room",
                }
            )
    return changes


def _faces_relations(relations: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in relations:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            source, relation_type, target = (str(value) for value in item)
            strength = "soft"
            parameters: dict[str, Any] = {}
        elif isinstance(item, dict):
            source = str(item.get("source") or item.get("subject") or "")
            relation_type = str(item.get("type") or item.get("predicate") or "")
            target = str(item.get("target") or item.get("object") or "")
            strength = str(item.get("strength") or "soft")
            parameters = (
                dict(item["parameters"])
                if isinstance(item.get("parameters"), dict)
                else {}
            )
        else:
            continue
        if relation_type in {"face", "facing"}:
            relation_type = "faces"
        if relation_type != "faces" or not source or not target:
            continue
        result.append(
            {
                "source": source,
                "target": target,
                "strength": strength if strength in {"hard", "soft"} else "soft",
                "parameters": parameters,
            }
        )
    return result


def evaluate_relation_facing(
    objects: list[dict[str, Any]], relations: Iterable[Any]
) -> list[dict[str, Any]]:
    by_id = {
        str(obj["id"]): obj
        for obj in objects
        if isinstance(obj, dict) and obj.get("id")
    }
    statuses: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    ordered = sorted(
        _faces_relations(relations),
        key=lambda item: (item["strength"] != "hard", item["source"], item["target"]),
    )
    for relation in ordered:
        source_id = str(relation["source"])
        target_id = str(relation["target"])
        if source_id in seen_sources:
            continue
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None:
            continue
        dx = float(target.get("x", 0.0)) - float(source.get("x", 0.0))
        dy = float(target.get("y", 0.0)) - float(source.get("y", 0.0))
        distance = math.hypot(dx, dy)
        if distance <= 1e-6:
            continue
        expected = (dx / distance, dy / distance)
        actual = world_front_vector(source)
        front = canonical_front(source)
        tolerance = float(
            relation["parameters"].get("tolerance_degrees", 25.0) or 25.0
        )
        error = _angle_error(actual, expected)
        statuses.append(
            {
                "object_id": source_id,
                "mode": "toward_object",
                "target_id": target_id,
                "strength": relation["strength"],
                "canonical_front_axis": front["axis"],
                "canonical_front_source": front["source"],
                "canonical_front_confidence": float(front["confidence"]),
                "world_front": [round(actual[0], 6), round(actual[1], 6)],
                "expected_front": [round(expected[0], 6), round(expected[1], 6)],
                "angle_error_degrees": round(error, 6),
                "tolerance_degrees": tolerance,
                "distance_to_target": round(distance, 6),
                "ok": error <= tolerance + 1e-6,
            }
        )
        seen_sources.add(source_id)
    return statuses


def apply_relation_facing_constraints(
    objects: list[dict[str, Any]], relations: Iterable[Any]
) -> list[dict[str, Any]]:
    by_id = {
        str(obj["id"]): obj
        for obj in objects
        if isinstance(obj, dict) and obj.get("id")
    }
    changes: list[dict[str, Any]] = []
    seen_sources: set[str] = set()
    ordered = sorted(
        _faces_relations(relations),
        key=lambda item: (item["strength"] != "hard", item["source"], item["target"]),
    )
    for relation in ordered:
        source_id = str(relation["source"])
        target_id = str(relation["target"])
        if source_id in seen_sources:
            continue
        source = by_id.get(source_id)
        target = by_id.get(target_id)
        if source is None or target is None:
            continue
        dx = float(target.get("x", 0.0)) - float(source.get("x", 0.0))
        dy = float(target.get("y", 0.0)) - float(source.get("y", 0.0))
        distance = math.hypot(dx, dy)
        if distance <= 1e-6:
            continue
        expected = (dx / distance, dy / distance)
        current = float(source.get("yaw", 0.0) or 0.0) % 360.0
        ranked = [
            (
                _angle_error(world_front_vector(source, yaw=candidate), expected),
                _circular_difference(candidate, current),
                candidate,
            )
            for candidate in CARDINAL_YAWS
        ]
        solved = min(ranked)[2]
        source["yaw"] = solved
        status = next(
            (
                item
                for item in evaluate_relation_facing(objects, [relation])
                if item["object_id"] == source_id
            ),
            None,
        )
        if status:
            source["relation_facing_resolution"] = status
        if _circular_difference(current, solved) > 1e-6:
            changes.append(
                {
                    "object_id": source_id,
                    "target_id": target_id,
                    "from_yaw": current,
                    "to_yaw": solved,
                    "reason": "functional_front_toward_object",
                }
            )
        seen_sources.add(source_id)
    return changes
