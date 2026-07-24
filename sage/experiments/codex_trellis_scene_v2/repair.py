from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from .composition import evaluate_composition
from .instance_groups import apply_instance_group_postprocess
from .orientation import apply_facing_constraints, apply_relation_facing_constraints
from .scene_graph import materialize_scene_graph
from .spatial_constraints import (
    compile_spatial_relations,
    evaluate_spatial_relations,
    relation_candidate_positions,
    spatial_relation_rank,
)
from .validator import aabb, door_clearance_box, footprint, overlap, walkway_exists


def _wall_constraint_is_hard(obj: dict[str, Any]) -> bool:
    if not obj.get("preferred_wall"):
        return False
    strength = obj.get("wall_constraint_strength")
    if strength is None:
        return True
    return str(strength) == "hard"


def _inside(obj: dict[str, Any], room: dict[str, Any]) -> bool:
    x0, y0, x1, y1 = aabb(obj)
    return x0 >= 0.05 and y0 >= 0.05 and x1 <= float(room["width"]) - 0.05 and y1 <= float(room["length"]) - 0.05


def _clamp(obj: dict[str, Any], room: dict[str, Any]) -> None:
    width, length = footprint(obj)
    obj["x"] = min(max(float(obj.get("x", 0.0)), width / 2.0 + 0.05), float(room["width"]) - width / 2.0 - 0.05)
    obj["y"] = min(max(float(obj.get("y", 0.0)), length / 2.0 + 0.05), float(room["length"]) - length / 2.0 - 0.05)


def _snap_wall(obj: dict[str, Any], room: dict[str, Any]) -> None:
    wall = obj.get("preferred_wall")
    width, length = footprint(obj)
    if wall == "north":
        obj["y"] = float(room["length"]) - length / 2.0 - 0.08
    elif wall == "south":
        obj["y"] = length / 2.0 + 0.08
    elif wall == "east":
        obj["x"] = float(room["width"]) - width / 2.0 - 0.08
    elif wall == "west":
        obj["x"] = width / 2.0 + 0.08
    _clamp(obj, room)


def _candidate_positions(obj: dict[str, Any], room: dict[str, Any]) -> Iterable[tuple[float, float]]:
    width = float(room["width"])
    length = float(room["length"])
    obj_width, obj_length = footprint(obj)
    wall = obj.get("preferred_wall")
    step = 0.25
    xs = [obj_width / 2.0 + 0.08 + step * i for i in range(max(1, int((width - obj_width - 0.16) / step) + 1))]
    ys = [obj_length / 2.0 + 0.08 + step * i for i in range(max(1, int((length - obj_length - 0.16) / step) + 1))]
    if wall == "north":
        y = length - obj_length / 2.0 - 0.08
        yield from ((x, y) for x in xs)
        if _wall_constraint_is_hard(obj):
            return
    elif wall == "south":
        y = obj_length / 2.0 + 0.08
        yield from ((x, y) for x in xs)
        if _wall_constraint_is_hard(obj):
            return
    elif wall == "east":
        x = width - obj_width / 2.0 - 0.08
        yield from ((x, y) for y in ys)
        if _wall_constraint_is_hard(obj):
            return
    elif wall == "west":
        x = obj_width / 2.0 + 0.08
        yield from ((x, y) for y in ys)
        if _wall_constraint_is_hard(obj):
            return
    yield from ((x, y) for y in ys for x in xs)


def _window_exclusion_boxes(
    plan: dict[str, Any], obj: dict[str, Any]
) -> list[tuple[float, float, float, float]]:
    architecture = plan.get("architecture")
    windows = architecture.get("windows", []) if isinstance(architecture, dict) else []
    room = plan["room"]
    room_width = float(room["width"])
    room_length = float(room["length"])
    obj_top = float(obj.get("z", 0.0)) + float(obj["dimensions"]["height"])
    boxes: list[tuple[float, float, float, float]] = []
    for window in windows:
        if not isinstance(window, dict) or obj_top <= float(window.get("sill_height", 0.0)) - 0.05:
            continue
        center = float(window.get("center", 0.0))
        half_width = float(window.get("width", 0.0)) / 2.0
        start, end = center - half_width, center + half_width
        wall = str(window.get("wall", ""))
        if wall == "north":
            boxes.append((start, room_length - 0.38, end, room_length))
        elif wall == "south":
            boxes.append((start, 0.0, end, 0.38))
        elif wall == "east":
            boxes.append((room_width - 0.38, start, room_width, end))
        elif wall == "west":
            boxes.append((0.0, start, 0.38, end))
    return boxes


def _blocked(
    obj: dict[str, Any],
    placed: list[dict[str, Any]],
    door_box: tuple[float, float, float, float],
    window_boxes: list[tuple[float, float, float, float]],
) -> bool:
    box = aabb(obj)
    return (
        overlap(box, door_box)
        or any(overlap(box, window_box) for window_box in window_boxes)
        or any(overlap(box, aabb(other), margin=0.04) for other in placed)
    )


def _wall_affinity_ok(obj: dict[str, Any], room: dict[str, Any]) -> bool:
    wall = str(obj.get("preferred_wall") or "")
    if not wall or not _wall_constraint_is_hard(obj):
        return True
    x0, y0, x1, y1 = aabb(obj)
    if wall == "north":
        distance = abs(float(room["length"]) - y1)
    elif wall == "south":
        distance = abs(y0)
    elif wall == "east":
        distance = abs(float(room["width"]) - x1)
    elif wall == "west":
        distance = abs(x0)
    else:
        return True
    return distance <= 0.35


def _repair_spatial_relations(
    plan: dict[str, Any],
    floor_objects: list[dict[str, Any]],
    *,
    max_sweeps: int = 4,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bounded deterministic grid search over typed 2D relation constraints."""

    relations = compile_spatial_relations(plan.get("relations", []))
    if not relations:
        return [], []
    room = plan["room"]
    door_box = door_clearance_box(plan)
    by_id = {
        str(obj["id"]): obj
        for obj in plan.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        outgoing.setdefault(str(relation["source"]), []).append(relation)
    sources = [
        obj
        for obj in floor_objects
        if str(obj.get("id") or "") in outgoing
    ]
    sources.sort(
        key=lambda obj: (
            not any(
                relation["strength"] == "hard"
                for relation in outgoing[str(obj["id"])]
            ),
            int(obj.get("priority", 50)),
            str(obj["id"]),
        )
    )
    changes: list[dict[str, Any]] = []

    for sweep in range(1, max_sweeps + 1):
        sweep_changed = False
        for obj in sources:
            object_id = str(obj["id"])
            status_by_id = {
                str(status["relation_id"]): status
                for status in evaluate_spatial_relations(
                    plan.get("objects", []), plan.get("relations", [])
                )
            }
            relevant = [
                status_by_id.get(str(relation["id"]))
                for relation in outgoing[object_id]
            ]
            if all(status is not None and status["ok"] for status in relevant):
                continue

            original = (
                float(obj.get("x", 0.0)),
                float(obj.get("y", 0.0)),
            )
            current_statuses = evaluate_spatial_relations(
                plan.get("objects", []), plan.get("relations", [])
            )
            current_relation_rank = spatial_relation_rank(current_statuses)
            candidate_positions: list[tuple[float, float]] = [original]
            candidate_positions.extend(_candidate_positions(obj, room))
            for relation in outgoing[object_id]:
                target = by_id.get(str(relation["target"]))
                if target is not None:
                    candidate_positions.extend(
                        relation_candidate_positions(obj, target, relation, by_id)
                    )

            seen: set[tuple[float, float]] = set()
            ranked: list[
                tuple[tuple[int, float, int, float, float, float, float], float, float]
            ] = []
            blockers = [other for other in floor_objects if other is not obj]
            window_boxes = _window_exclusion_boxes(plan, obj)
            preserve_walkway = walkway_exists(plan, floor_objects)
            current_hard_composition = sum(
                1
                for violation in evaluate_composition(plan)[0]
                if violation.get("severity") == "hard"
            )
            for x, y in candidate_positions:
                key = round(float(x), 6), round(float(y), 6)
                if key in seen:
                    continue
                seen.add(key)
                candidate = deepcopy(obj)
                candidate["x"], candidate["y"] = float(x), float(y)
                if _wall_constraint_is_hard(candidate):
                    _snap_wall(candidate, room)
                x, y = float(candidate["x"]), float(candidate["y"])
                if not _inside(candidate, room) or not _wall_affinity_ok(candidate, room):
                    continue
                if _blocked(candidate, blockers, door_box, window_boxes):
                    continue
                previous_x, previous_y = float(obj["x"]), float(obj["y"])
                obj["x"], obj["y"] = x, y
                if preserve_walkway and not walkway_exists(plan, floor_objects):
                    obj["x"], obj["y"] = previous_x, previous_y
                    continue
                candidate_hard_composition = sum(
                    1
                    for violation in evaluate_composition(plan)[0]
                    if violation.get("severity") == "hard"
                )
                if candidate_hard_composition > current_hard_composition:
                    obj["x"], obj["y"] = previous_x, previous_y
                    continue
                statuses = evaluate_spatial_relations(
                    plan.get("objects", []), plan.get("relations", [])
                )
                obj["x"], obj["y"] = previous_x, previous_y
                relation_rank = spatial_relation_rank(statuses)
                distance = (x - original[0]) ** 2 + (y - original[1]) ** 2
                rank = (
                    *relation_rank,
                    round(distance, 8),
                    round(x, 6),
                    round(y, 6),
                )
                ranked.append((rank, x, y))

            if not ranked:
                continue
            best_rank, best_x, best_y = min(ranked, key=lambda item: item[0])
            if best_rank[:4] >= current_relation_rank:
                continue
            obj["x"], obj["y"] = best_x, best_y
            changes.append(
                {
                    "object_id": object_id,
                    "from": original,
                    "to": (best_x, best_y),
                    "reason": "typed_relation_csp_search",
                    "sweep": sweep,
                    "rank_before": list(current_relation_rank),
                    "rank_after": list(best_rank[:4]),
                }
            )
            sweep_changed = True
        if not sweep_changed:
            break

    unresolved = [
        status
        for status in evaluate_spatial_relations(
            plan.get("objects", []), plan.get("relations", [])
        )
        if not status["ok"]
    ]
    return changes, unresolved


def deterministic_repair(plan: dict[str, Any], iteration: int = 1) -> dict[str, Any]:
    repaired = deepcopy(plan)
    orientation_changes = apply_facing_constraints(repaired["objects"])
    room = repaired["room"]
    floor = [obj for obj in repaired["objects"] if obj.get("placement_type", "floor") == "floor"]
    wall = [obj for obj in repaired["objects"] if obj.get("placement_type") == "wall"]
    coverings = [obj for obj in repaired["objects"] if obj.get("placement_type") == "floor_covering"]
    supports = [obj for obj in repaired["objects"] if obj.get("placement_type") == "support"]
    handled = {id(obj) for obj in floor + wall + coverings + supports}
    others = [obj for obj in repaired["objects"] if id(obj) not in handled]
    floor.sort(key=lambda item: (-int(item.get("priority", 50)), str(item["id"])))
    placed: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = [
        {
            "object_id": item["object_id"],
            "from_yaw": item["from_yaw"],
            "to_yaw": item["to_yaw"],
            "reason": item["reason"],
        }
        for item in orientation_changes
    ]
    door_box = door_clearance_box(repaired)

    for obj in floor:
        original = (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)))
        window_boxes = _window_exclusion_boxes(repaired, obj)
        _clamp(obj, room)
        _snap_wall(obj, room)
        if _blocked(obj, placed, door_box, window_boxes):
            ranked: list[tuple[float, float, float]] = []
            for x, y in _candidate_positions(obj, room):
                candidate = deepcopy(obj)
                candidate["x"], candidate["y"] = x, y
                if not _inside(candidate, room) or _blocked(
                    candidate, placed, door_box, window_boxes
                ):
                    continue
                distance = (x - original[0]) ** 2 + (y - original[1]) ** 2
                ranked.append((distance, x, y))
            if ranked:
                _, obj["x"], obj["y"] = min(ranked, key=lambda item: (item[0], item[1], item[2]))
        placed.append(obj)
        current = (float(obj["x"]), float(obj["y"]))
        if current != original:
            changes.append({"object_id": obj["id"], "from": original, "to": current, "reason": "hard_constraint_repair"})

    relation_changes, unresolved_relations = _repair_spatial_relations(
        repaired, floor
    )
    changes.extend(relation_changes)
    instance_group_resolution = apply_instance_group_postprocess(repaired)
    for result in instance_group_resolution.get("results", []):
        if result.get("status") != "adjusted":
            continue
        for object_id, after in result.get("after", {}).items():
            before = result.get("before", {}).get(object_id)
            if before != after:
                changes.append(
                    {
                        "object_id": object_id,
                        "from": before,
                        "to": after,
                        "reason": "instance_group_after_layout_adjustment",
                        "group_id": result.get("group_id"),
                    }
                )

    for obj in wall:
        original = (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)), float(obj.get("z", 0.0)))
        _clamp(obj, room)
        _snap_wall(obj, room)
        obj["z"] = float(obj.get("mount_height") or obj.get("z", 1.5))
        current = (float(obj["x"]), float(obj["y"]), float(obj["z"]))
        if current != original:
            changes.append({"object_id": obj["id"], "from": original, "to": current, "reason": "wall_mount_snap"})

    for obj in coverings:
        original = (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)), float(obj.get("z", 0.0)))
        _clamp(obj, room)
        obj["z"] = 0.01
        current = (float(obj["x"]), float(obj["y"]), float(obj["z"]))
        if current != original:
            changes.append({"object_id": obj["id"], "from": original, "to": current, "reason": "floor_covering_snap"})

    by_id = {str(obj["id"]): obj for obj in floor + wall + coverings + others}
    for obj in supports:
        support = by_id.get(str(obj.get("support_id")))
        if not support:
            continue
        original = (float(obj.get("x", 0.0)), float(obj.get("y", 0.0)), float(obj.get("z", 0.0)))
        offset = obj.get("support_offset") or [0.0, 0.0]
        dx, dy = float(offset[0]), float(offset[1])
        quarter_turns = int(round(float(support.get("yaw", 0.0)) / 90.0)) % 4
        if quarter_turns == 1:
            dx, dy = -dy, dx
        elif quarter_turns == 2:
            dx, dy = -dx, -dy
        elif quarter_turns == 3:
            dx, dy = dy, -dx
        obj["x"] = float(support["x"]) + dx
        obj["y"] = float(support["y"]) + dy
        obj["z"] = float(support.get("z", 0.0)) + float(support["dimensions"]["height"])
        obj["yaw"] = float(support.get("yaw", 0.0))
        current = (obj["x"], obj["y"], obj["z"])
        if current != original:
            changes.append({"object_id": obj["id"], "from": original, "to": current, "reason": "support_snap"})

    order = {str(obj["id"]): index for index, obj in enumerate(plan["objects"])}
    repaired["objects"] = sorted(
        floor + wall + coverings + supports + others,
        key=lambda item: order[str(item["id"])],
    )
    changes.extend(
        apply_relation_facing_constraints(
            repaired["objects"], repaired.get("relations", [])
        )
    )
    repaired.setdefault("repair_history", []).append(
        {
            "iteration": iteration,
            "method": "deterministic_sdk",
            "changes": changes,
            "spatial_relation_search": {
                "method": "bounded_grid_csp",
                "change_count": len(relation_changes),
                "unresolved_count": len(unresolved_relations),
                "unresolved": unresolved_relations,
            },
            "instance_group_postprocess": deepcopy(instance_group_resolution),
        }
    )
    if isinstance(repaired.get("scene_graph"), dict):
        repaired["scene_graph"] = materialize_scene_graph(
            repaired["scene_graph"], repaired["objects"]
        )
    return repaired
