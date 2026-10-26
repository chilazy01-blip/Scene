from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Any

from .composition import evaluate_composition
from .asset_usage import asset_usage_violations
from .dimensions import AXES
from .instance_groups import validate_instance_groups
from .orientation import evaluate_facing, evaluate_relation_facing
from .scene_graph import validate_typed_scene_graph
from .spatial_constraints import evaluate_spatial_relations


OPPOSITE_WALL = {
    "north": "south",
    "south": "north",
    "east": "west",
    "west": "east",
}


def footprint(obj: dict[str, Any]) -> tuple[float, float]:
    dims = obj["dimensions"]
    width = float(dims["width"])
    length = float(dims["length"])
    quarter_turn = int(round(float(obj.get("yaw", 0.0)) / 90.0)) % 2 == 1
    return (length, width) if quarter_turn else (width, length)


def aabb(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    width, length = footprint(obj)
    x = float(obj.get("x", 0.0))
    y = float(obj.get("y", 0.0))
    return x - width / 2.0, y - length / 2.0, x + width / 2.0, y + length / 2.0


def overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], margin: float = 0.0) -> bool:
    return not (
        a[2] + margin <= b[0]
        or b[2] + margin <= a[0]
        or a[3] + margin <= b[1]
        or b[3] + margin <= a[1]
    )


def door_clearance_box(plan: dict[str, Any]) -> tuple[float, float, float, float]:
    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    architecture = plan.get("architecture")
    doors = architecture.get("doors", []) if isinstance(architecture, dict) else []
    door = doors[0] if doors and isinstance(doors[0], dict) else None
    if not door:
        return width - 1.1, 0.15, width, 1.35
    wall = str(door.get("wall", "east"))
    center = float(door.get("center", 0.75))
    opening_width = float(door.get("width", 0.9))
    depth = float(door.get("clearance_depth", 1.1))
    margin = float(door.get("clearance_margin", 0.15))
    start = center - opening_width / 2.0 - margin
    end = center + opening_width / 2.0 + margin
    if wall == "west":
        return 0.0, start, depth, end
    if wall == "north":
        return start, length - depth, end, length
    if wall == "south":
        return start, 0.0, end, depth
    return width - depth, start, width, end


def _wall_distance(obj: dict[str, Any], room: dict[str, Any], wall: str) -> float:
    x0, y0, x1, y1 = aabb(obj)
    if wall == "north":
        return abs(float(room["length"]) - y1)
    if wall == "south":
        return abs(y0)
    if wall == "east":
        return abs(float(room["width"]) - x1)
    if wall == "west":
        return abs(x0)
    return 0.0


def _opening_interval(opening: dict[str, Any]) -> tuple[float, float]:
    center = float(opening.get("center", 0.0))
    width = float(opening.get("width", 0.0))
    return center - width / 2.0, center + width / 2.0


def _architecture_violations(
    plan: dict[str, Any], blocking_objects: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    room = plan["room"]
    room_height = float(room["height"])
    architecture = plan.get("architecture")
    violations: list[dict[str, Any]] = []
    if not isinstance(architecture, dict):
        return (
            [{"type": "architecture_missing", "severity": "hard"}],
            {"door_count": 0, "window_count": 0, "floor_material_present": False},
        )

    requirements = architecture.get("requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    valid_walls = {"north", "south", "east", "west"}
    walls = {str(item) for item in architecture.get("walls", [])}
    expected_wall_count = int(requirements.get("enclosing_wall_count", 4))
    if len(walls) != expected_wall_count or walls != valid_walls:
        violations.append(
            {
                "type": "architecture_enclosing_walls",
                "severity": "hard",
                "expected": sorted(valid_walls),
                "actual": sorted(walls),
            }
        )
    doors = [item for item in architecture.get("doors", []) if isinstance(item, dict)]
    windows = [item for item in architecture.get("windows", []) if isinstance(item, dict)]
    expected_doors = int(requirements.get("door_count", 1))
    min_windows = int(requirements.get("window_count_min", 0))
    max_windows = int(requirements.get("window_count_max", max(min_windows, len(windows))))
    if len(doors) != expected_doors:
        violations.append(
            {
                "type": "architecture_door_count",
                "severity": "hard",
                "expected": expected_doors,
                "actual": len(doors),
            }
        )
    if not min_windows <= len(windows) <= max_windows:
        violations.append(
            {
                "type": "architecture_window_count",
                "severity": "hard",
                "minimum": min_windows,
                "maximum": max_windows,
                "actual": len(windows),
            }
        )

    floor = architecture.get("floor")
    floor = floor if isinstance(floor, dict) else {}
    floor_material = floor.get("material")
    floor_material = floor_material if isinstance(floor_material, dict) else {}
    floor_material_present = bool(
        floor_material.get("texture_type") or floor_material.get("texture_image")
    )
    if bool(requirements.get("floor_material_required", True)) and not floor_material_present:
        violations.append({"type": "floor_material_missing", "severity": "hard"})

    wall_finish = architecture.get("wall_finish")
    wall_finish = wall_finish if isinstance(wall_finish, dict) else {}
    default_wall_material = wall_finish.get("default")
    default_wall_material = (
        default_wall_material if isinstance(default_wall_material, dict) else {}
    )
    wall_material_present = bool(
        default_wall_material.get("texture_type")
        or default_wall_material.get("texture_image")
    )
    if bool(requirements.get("wall_material_required", True)) and not wall_material_present:
        violations.append({"type": "wall_material_missing", "severity": "hard"})
    wall_material_overrides = wall_finish.get("overrides")
    wall_material_overrides = (
        wall_material_overrides if isinstance(wall_material_overrides, dict) else {}
    )
    invalid_override_walls = sorted(
        str(wall) for wall in wall_material_overrides if str(wall) not in valid_walls
    )
    if invalid_override_walls:
        violations.append(
            {
                "type": "wall_material_override_wall_invalid",
                "severity": "hard",
                "walls": invalid_override_walls,
            }
        )
    max_override_walls = int(wall_finish.get("max_override_walls", 1) or 1)
    if len(wall_material_overrides) > max_override_walls:
        violations.append(
            {
                "type": "wall_material_override_count",
                "severity": "hard",
                "maximum": max_override_walls,
                "actual": len(wall_material_overrides),
            }
        )
    missing_override_materials = sorted(
        str(wall)
        for wall, material in wall_material_overrides.items()
        if not isinstance(material, dict)
        or not (material.get("texture_type") or material.get("texture_image"))
    )
    if missing_override_materials:
        violations.append(
            {
                "type": "wall_material_override_missing",
                "severity": "hard",
                "walls": missing_override_materials,
            }
        )

    openings = [("door", item) for item in doors] + [("window", item) for item in windows]
    for opening_type, opening in openings:
        wall = str(opening.get("wall", ""))
        extent = float(room["width"] if wall in {"north", "south"} else room["length"])
        start, end = _opening_interval(opening)
        bottom = 0.0 if opening_type == "door" else float(opening.get("sill_height", 0.0))
        top = bottom + float(opening.get("height", 0.0))
        if (
            wall not in valid_walls
            or start < 0.05
            or end > extent - 0.05
            or end <= start
            or bottom < 0.0
            or top > room_height + 0.001
            or top <= bottom
        ):
            violations.append(
                {
                    "type": "architecture_opening_boundary",
                    "severity": "hard",
                    "opening_type": opening_type,
                    "opening_id": opening.get("id"),
                }
            )

    for index, (left_type, left) in enumerate(openings):
        for right_type, right in openings[index + 1 :]:
            if left.get("wall") != right.get("wall"):
                continue
            left_interval = _opening_interval(left)
            right_interval = _opening_interval(right)
            left_bottom = 0.0 if left_type == "door" else float(left.get("sill_height", 0.0))
            right_bottom = 0.0 if right_type == "door" else float(right.get("sill_height", 0.0))
            left_vertical = (left_bottom, left_bottom + float(left.get("height", 0.0)))
            right_vertical = (right_bottom, right_bottom + float(right.get("height", 0.0)))
            if not (
                left_interval[1] <= right_interval[0]
                or right_interval[1] <= left_interval[0]
                or left_vertical[1] <= right_vertical[0]
                or right_vertical[1] <= left_vertical[0]
            ):
                violations.append(
                    {
                        "type": "architecture_opening_overlap",
                        "severity": "hard",
                        "openings": [left.get("id"), right.get("id")],
                    }
                )

    constraint_overrides = architecture.get("constraint_overrides")
    constraint_overrides = constraint_overrides if isinstance(constraint_overrides, dict) else {}
    shared_walls = sorted(
        {str(item.get("wall")) for item in doors}
        & {str(item.get("wall")) for item in windows}
    )
    if shared_walls and not bool(constraint_overrides.get("door_window_same_wall")):
        violations.append(
            {
                "type": "door_window_same_wall",
                "severity": "soft",
                "walls": shared_walls,
                "reason": "doors and windows normally use different walls",
            }
        )

    primary_door_wall = str(doors[0].get("wall")) if doors else ""
    main_window_wall = str(windows[0].get("wall")) if windows else ""
    preferred_opposite_wall = OPPOSITE_WALL.get(primary_door_wall)
    door_window_opposite = bool(
        preferred_opposite_wall and main_window_wall == preferred_opposite_wall
    )
    opposite_preferred = bool(requirements.get("window_opposite_door_preferred"))
    if (
        opposite_preferred
        and doors
        and windows
        and not door_window_opposite
        and not bool(constraint_overrides.get("door_window_opposite_wall"))
    ):
        violations.append(
            {
                "type": "door_window_not_opposite",
                "severity": "soft",
                "door_wall": primary_door_wall,
                "window_wall": main_window_wall,
                "preferred_window_wall": preferred_opposite_wall,
                "reason": "bedroom main window preferably faces the entry wall",
            }
        )

    for window in windows:
        wall = str(window.get("wall", ""))
        window_start, window_end = _opening_interval(window)
        sill = float(window.get("sill_height", 0.0))
        for obj in blocking_objects:
            from .furnishing_groups import allowed_window_treatment
            if allowed_window_treatment(obj, window):
                continue
            if _wall_distance(obj, room, wall) > 0.38:
                continue
            x0, y0, x1, y1 = aabb(obj)
            obj_start, obj_end = (x0, x1) if wall in {"north", "south"} else (y0, y1)
            obj_top = float(obj.get("z", 0.0)) + float(obj["dimensions"]["height"])
            if obj_end > window_start and obj_start < window_end and obj_top > sill - 0.05:
                violations.append(
                    {
                        "type": "window_obstruction",
                        "severity": "hard",
                        "window_id": window.get("id"),
                        "object_id": obj.get("id"),
                    }
                )

    return violations, {
        "wall_count": len(walls),
        "door_count": len(doors),
        "window_count": len(windows),
        "door_walls": sorted({str(item.get("wall")) for item in doors}),
        "window_walls": sorted({str(item.get("wall")) for item in windows}),
        "door_window_same_wall": bool(shared_walls),
        "door_window_same_wall_overridden": bool(
            constraint_overrides.get("door_window_same_wall")
        ),
        "door_window_opposite_wall_preferred": opposite_preferred,
        "door_window_opposite_wall": door_window_opposite,
        "door_window_opposite_wall_overridden": bool(
            constraint_overrides.get("door_window_opposite_wall")
        ),
        "floor_material_present": floor_material_present,
        "floor_material_id": floor_material.get("material_id"),
        "floor_texture_type": floor_material.get("texture_type"),
        "wall_material_present": wall_material_present,
        "wall_material_id": default_wall_material.get("material_id"),
        "wall_texture_type": default_wall_material.get("texture_type"),
        "wall_material_overrides": {
            str(wall): material.get("material_id")
            for wall, material in wall_material_overrides.items()
            if isinstance(material, dict)
        },
    }


def walkway_status(plan: dict[str, Any], floor_objects: list[dict[str, Any]]) -> dict[str, Any]:
    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    step = 0.2
    clearance = 0.32
    nx = max(2, int(width / step) + 1)
    ny = max(2, int(length / step) + 1)
    blocked: set[tuple[int, int]] = set()
    boxes = [aabb(obj) for obj in floor_objects]
    for ix in range(nx):
        x = min(width, ix * step)
        for iy in range(ny):
            y = min(length, iy * step)
            if any(
                box[0] - clearance <= x <= box[2] + clearance
                and box[1] - clearance <= y <= box[3] + clearance
                for box in boxes
            ):
                blocked.add((ix, iy))

    def nearest_free(target_x: float, target_y: float) -> tuple[int, int] | None:
        ranked = sorted(
            (
                ((ix * step - target_x) ** 2 + (iy * step - target_y) ** 2, (ix, iy))
                for ix in range(nx)
                for iy in range(ny)
                if (ix, iy) not in blocked
            ),
            key=lambda item: item[0],
        )
        return ranked[0][1] if ranked else None

    doors = plan.get('architecture', {}).get('doors', [])
    door = doors[0] if doors else {'wall': 'east', 'center': .75}
    center = float(door.get('center', .75))
    entry = {'west': (.35, center), 'east': (width-.35, center),
             'south': (center, .35), 'north': (center, length-.35)}[door.get('wall', 'east')]
    start = nearest_free(*entry)
    goal = nearest_free(width / 2.0, length / 2.0)
    if not start or not goal:
        return {'exists': False, 'barrier_cells': nx*ny, 'frontier_distance': nx+ny, 'reachable_cells': 0}
    queue = deque([start])
    visited = {start}
    while queue:
        current = queue.popleft()
        if current == goal:
            return {'exists': True, 'barrier_cells': 0, 'frontier_distance': 0, 'reachable_cells': len(visited)}
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = current[0] + dx, current[1] + dy
            if not (0 <= neighbor[0] < nx and 0 <= neighbor[1] < ny):
                continue
            if neighbor in blocked or neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    # A 0/1 traversal estimates how many blocked cells separate the connected
    # regions. It guides joint repair even when moving the farther obstruction
    # alone cannot enlarge the entry region. It never changes the pass/fail gate.
    costs = {start: 0}; pending = deque([start])
    while pending:
        current = pending.popleft()
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            neighbor = current[0]+dx, current[1]+dy
            if not (0 <= neighbor[0] < nx and 0 <= neighbor[1] < ny):
                continue
            penalty = int(neighbor in blocked)
            value = costs[current]+penalty
            if value < costs.get(neighbor, nx*ny):
                costs[neighbor] = value
                (pending.append if penalty else pending.appendleft)(neighbor)
    return {'exists': False, 'barrier_cells': costs.get(goal,nx*ny),
            'frontier_distance': min(abs(p[0]-goal[0])+abs(p[1]-goal[1]) for p in visited),
            'reachable_cells': len(visited)}


def walkway_exists(plan: dict[str, Any], floor_objects: list[dict[str, Any]]) -> bool:
    return walkway_status(plan, floor_objects)['exists']


def _facing_violations(
    objects: list[dict[str, Any]], relations: list[Any], room: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    violations = [failure for obj in objects for failure in asset_usage_violations(obj, room)]
    wall_statuses = [
        status for obj in objects if (status := evaluate_facing(obj, room))
    ]
    relation_statuses = evaluate_relation_facing(objects, relations)
    statuses = wall_statuses + relation_statuses
    for status in statuses:
        if status["ok"]:
            continue
        confidence = float(status["canonical_front_confidence"])
        severity = (
            str(status.get("strength"))
            if status.get("mode") == "toward_object"
            else ("hard" if confidence >= 0.75 else "soft")
        )
        violations.append(
            {
                "type": "functional_facing_direction",
                "severity": severity if severity in {"hard", "soft"} else "soft",
                **status,
            }
        )
    errors = [float(item["angle_error_degrees"]) for item in statuses]
    return violations, {
        "checked_count": len(statuses),
        "wall_facing_count": len(wall_statuses),
        "target_facing_count": len(relation_statuses),
        "valid_count": sum(1 for item in statuses if item["ok"]),
        "invalid_count": sum(1 for item in statuses if not item["ok"]),
        "metadata_count": sum(
            1 for item in statuses if item["canonical_front_source"] != "policy_fallback"
        ),
        "fallback_count": sum(
            1 for item in statuses if item["canonical_front_source"] == "policy_fallback"
        ),
        "max_angle_error_degrees": round(max(errors), 6) if errors else 0.0,
    }


def _spatial_relation_violations(
    objects: list[dict[str, Any]], relations: list[Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    statuses = evaluate_spatial_relations(objects, relations)
    violations: list[dict[str, Any]] = []
    for status in statuses:
        if status.get("role_assignment_ok") is False:
            violations.append(
                {
                    **status,
                    "type": "side_role_assignment",
                    "relation_type": str(status["type"]),
                    "severity": "hard",
                }
            )
        elif not status.get("relation_ok", status["ok"]):
            violations.append(
                {
                    **status,
                    "type": "spatial_relation_constraint",
                    "relation_type": str(status["type"]),
                    "severity": str(status["strength"]),
                }
            )
    type_counts: dict[str, int] = {}
    invalid_type_counts: dict[str, int] = {}
    for status in statuses:
        relation_type = str(status["type"])
        type_counts[relation_type] = type_counts.get(relation_type, 0) + 1
        if not status["ok"]:
            invalid_type_counts[relation_type] = (
                invalid_type_counts.get(relation_type, 0) + 1
            )
    side_role_statuses = [status for status in statuses if status.get("role_locked")]
    return violations, {
        "evaluation_domain": "cardinal_2d_footprint_csp",
        "checked_count": len(statuses),
        "valid_count": sum(1 for status in statuses if status["ok"]),
        "invalid_count": sum(1 for status in statuses if not status["ok"]),
        "hard_invalid_count": sum(
            1
            for status in statuses
            if not status["ok"] and status["strength"] == "hard"
        ),
        "soft_invalid_count": sum(
            1
            for status in statuses
            if not status["ok"] and status["strength"] == "soft"
        ),
        "max_residual": round(
            max((float(status["residual"]) for status in statuses), default=0.0),
            6,
        ),
        "type_counts": dict(sorted(type_counts.items())),
        "invalid_type_counts": dict(sorted(invalid_type_counts.items())),
        "side_role_assignment": {
            "checked_count": len(side_role_statuses),
            "valid_count": sum(
                1 for status in side_role_statuses if status["role_assignment_ok"]
            ),
            "invalid_count": sum(
                1 for status in side_role_statuses if not status["role_assignment_ok"]
            ),
        },
        "statuses": statuses,
    }


def _relation_violation_id(violation: dict[str, Any]) -> str | None:
    relation_id = str(violation.get("relation_id") or "")
    if relation_id:
        return relation_id
    if (
        str(violation.get("type") or "") == "functional_facing_direction"
        and str(violation.get("mode") or "") == "toward_object"
    ):
        source = str(violation.get("object_id") or "")
        target = str(violation.get("target_id") or "")
        if source and target:
            return f"relation:{source}:faces:{target}"
    return None


def _relation_violation_endpoints(violation: dict[str, Any]) -> set[str]:
    source = str(
        violation.get("source") or violation.get("object_id") or ""
    )
    target = str(
        violation.get("target") or violation.get("target_id") or ""
    )
    return {source, target} - {""}


def _constraint_scopes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    direct = plan.get("constraint_scopes")
    if isinstance(direct, list):
        return [scope for scope in direct if isinstance(scope, dict)]
    graph = plan.get("scene_graph")
    if isinstance(graph, dict) and isinstance(graph.get("constraint_scopes"), list):
        return [
            scope for scope in graph["constraint_scopes"] if isinstance(scope, dict)
        ]
    return []


def _aggregate_constraint_scope_failures(
    plan: dict[str, Any], violations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a reporting-only view over raw relation failures.

    Relations connect only when an accepted scope references both and their endpoint
    sets overlap. Scope overlap alone never merges unrelated failures.
    """

    raw_by_relation: dict[str, list[dict[str, Any]]] = {}
    for violation in violations:
        relation_id = _relation_violation_id(violation)
        if relation_id:
            raw_by_relation.setdefault(relation_id, []).append(violation)
    endpoints_by_relation = {
        relation_id: {
            endpoint
            for violation in relation_violations
            for endpoint in _relation_violation_endpoints(violation)
        }
        for relation_id, relation_violations in raw_by_relation.items()
    }

    adjacency: dict[str, set[str]] = {
        relation_id: set() for relation_id in raw_by_relation
    }
    scopes_by_relation: dict[str, set[str]] = {}
    membership_inferred_by_scope: dict[str, set[str]] = {}
    for scope in _constraint_scopes(plan):
        scope_id = str(scope.get("scope_id") or "")
        if not scope_id:
            continue
        failed_refs: list[tuple[str, set[str]]] = []
        failed_ref_ids: set[str] = set()
        for ref in scope.get("relation_refs", []):
            if not isinstance(ref, dict):
                continue
            relation_id = str(ref.get("id") or "")
            if relation_id not in raw_by_relation:
                continue
            endpoints = {
                str(ref.get("source") or ""),
                str(ref.get("target") or ""),
            } - {""}
            failed_refs.append((relation_id, endpoints))
            failed_ref_ids.add(relation_id)
            scopes_by_relation.setdefault(relation_id, set()).add(scope_id)
        member_ids = {
            str(member.get("object_id") or "")
            for member in scope.get("members", [])
            if isinstance(member, dict)
        } - {""}
        for relation_id, endpoints in endpoints_by_relation.items():
            if (
                relation_id not in failed_ref_ids
                and len(endpoints) == 2
                and endpoints <= member_ids
            ):
                failed_refs.append((relation_id, endpoints))
                failed_ref_ids.add(relation_id)
                scopes_by_relation.setdefault(relation_id, set()).add(scope_id)
                membership_inferred_by_scope.setdefault(scope_id, set()).add(
                    relation_id
                )
        for index, (left_id, left_endpoints) in enumerate(failed_refs):
            for right_id, right_endpoints in failed_refs[index + 1 :]:
                if left_endpoints & right_endpoints:
                    adjacency[left_id].add(right_id)
                    adjacency[right_id].add(left_id)

    scoped_relation_ids = set(scopes_by_relation)
    groups: list[dict[str, Any]] = []
    visited: set[str] = set()
    for start in sorted(scoped_relation_ids):
        if start in visited:
            continue
        stack = [start]
        component: set[str] = set()
        while stack:
            relation_id = stack.pop()
            if relation_id in visited or relation_id not in scoped_relation_ids:
                continue
            visited.add(relation_id)
            component.add(relation_id)
            stack.extend(sorted(adjacency.get(relation_id, set()) - visited))

        component_scopes = sorted(
            {
                scope_id
                for relation_id in component
                for scope_id in scopes_by_relation.get(relation_id, set())
            }
        )
        component_violations = [
            violation
            for relation_id in sorted(component)
            for violation in raw_by_relation[relation_id]
        ]
        endpoints = {
            endpoint
            for relation_id in component
            for endpoint in endpoints_by_relation.get(relation_id, set())
        }
        residuals = [
            float(violation.get("residual", 0.0) or 0.0)
            for violation in component_violations
        ]
        severity = (
            "hard"
            if any(str(item.get("severity") or "") == "hard" for item in component_violations)
            else "soft"
        )
        membership_inferred_relation_ids = sorted(
            {
                relation_id
                for scope_id in component_scopes
                for relation_id in membership_inferred_by_scope.get(scope_id, set())
                if relation_id in component
            }
        )
        groups.append(
            {
                "aggregate_id": "constraint_scope_failure:"
                + "+".join(component_scopes)
                + f":{len(groups) + 1}",
                "scope_ids": component_scopes,
                "primary_scope_id": component_scopes[0],
                "severity": severity,
                "failed_relation_count": len(component),
                "failed_relation_ids": sorted(component),
                "membership_inferred_relation_ids": membership_inferred_relation_ids,
                "failed_node_ids": sorted(endpoints),
                "raw_violation_count": len(component_violations),
                "raw_violation_types": sorted(
                    {str(item.get("type") or "") for item in component_violations}
                ),
                "max_residual": round(max(residuals, default=0.0), 6),
                "sum_residual": round(sum(residuals), 6),
            }
        )

    unscoped = sorted(set(raw_by_relation) - scoped_relation_ids)
    hard_unscoped = sum(
        1
        for relation_id in unscoped
        if any(
            str(item.get("severity") or "") == "hard"
            for item in raw_by_relation[relation_id]
        )
    )
    soft_unscoped = len(unscoped) - hard_unscoped
    hard_groups = sum(1 for group in groups if group["severity"] == "hard")
    soft_groups = len(groups) - hard_groups
    return {
        "schema": "codex_trellis_constraint_scope_failures_v1",
        "reporting_only": True,
        "changes_validation_ok": False,
        "raw_relation_failure_count": len(raw_by_relation),
        "scoped_raw_relation_failure_count": len(scoped_relation_ids),
        "membership_inferred_relation_count": len(
            {
                relation_id
                for relation_ids in membership_inferred_by_scope.values()
                for relation_id in relation_ids
            }
        ),
        "scope_failure_count": len(groups),
        "hard_scope_failure_count": hard_groups,
        "soft_scope_failure_count": soft_groups,
        "unscoped_relation_failure_count": len(unscoped),
        "hard_unscoped_relation_failure_count": hard_unscoped,
        "soft_unscoped_relation_failure_count": soft_unscoped,
        "grouped_relation_failure_count": len(groups) + len(unscoped),
        "hard_grouped_relation_failure_count": hard_groups + hard_unscoped,
        "soft_grouped_relation_failure_count": soft_groups + soft_unscoped,
        "unscoped_relation_ids": unscoped,
        "groups": groups,
    }


def validate_layout(plan: dict[str, Any]) -> dict[str, Any]:
    room = plan["room"]
    width = float(room["width"])
    length = float(room["length"])
    objects = [obj for obj in plan.get("objects", []) if isinstance(obj, dict)]
    by_id = {str(obj["id"]): obj for obj in objects}
    violations: list[dict[str, Any]] = []
    door_box = door_clearance_box(plan)
    budget = plan.get("object_budget") if isinstance(plan.get("object_budget"), dict) else {}
    hard_min = int(budget.get("hard_min", 0))
    target_max = int(budget.get("target_max", max(len(objects), hard_min)))
    max_auto_inferred = int(budget.get("max_auto_inferred_objects", 0))
    hard_runtime_limit = int(budget.get("hard_runtime_limit", 40))
    required_ids = {str(item) for item in budget.get("required_object_ids", [])}
    auto_inferred = [
        obj for obj in objects if obj.get("provenance") == "codex_inferred_optional"
    ]
    scene_graph = plan.get("scene_graph")
    scene_graph_metrics = {
        "present": isinstance(scene_graph, dict),
        "validation": {"ok": True, "error_count": 0, "errors": []},
        "stats": {},
    }
    if isinstance(scene_graph, dict):
        graph_validation = validate_typed_scene_graph(scene_graph)
        scene_graph_metrics = {
            "present": True,
            "validation": graph_validation,
            "stats": deepcopy(scene_graph.get("stats", {})),
        }
        for error in graph_validation["errors"]:
            violations.append(
                {
                    "type": "typed_scene_graph_invalid",
                    "severity": "hard",
                    "reason": error,
                }
            )

    missing_required = sorted(required_ids - set(by_id))
    for object_id in missing_required:
        violations.append(
            {"type": "required_object_missing", "severity": "hard", "object_id": object_id}
        )
    if len(objects) < hard_min:
        violations.append(
            {
                "type": "object_count_below_hard_min",
                "severity": "hard",
                "object_count": len(objects),
                "hard_min": hard_min,
            }
        )
    if len(objects) > hard_runtime_limit:
        violations.append(
            {
                "type": "object_count_above_runtime_safety_limit",
                "severity": "hard",
                "object_count": len(objects),
                "hard_runtime_limit": hard_runtime_limit,
            }
        )
    if len(auto_inferred) > max_auto_inferred:
        violations.append(
            {
                "type": "auto_inferred_object_budget_exceeded",
                "severity": "hard",
                "auto_inferred_count": len(auto_inferred),
                "maximum": max_auto_inferred,
            }
        )

    floor_objects = [obj for obj in objects if obj.get("placement_type", "floor") == "floor"]
    architecture_violations, architecture_metrics = _architecture_violations(
        plan,
        [
            obj
            for obj in objects
            if obj.get("placement_type", "floor") in {"floor", "wall"}
        ],
    )
    violations.extend(architecture_violations)
    facing_violations, facing_metrics = _facing_violations(
        objects, list(plan.get("relations", [])), room
    )
    violations.extend(facing_violations)
    spatial_relation_violations, spatial_relation_metrics = (
        _spatial_relation_violations(objects, list(plan.get("relations", [])))
    )
    violations.extend(spatial_relation_violations)
    dimension_statuses: dict[str, int] = {}
    dimension_policy_modes: dict[str, int] = {}
    max_dimension_scale_anisotropy = 0.0
    for obj in objects:
        policy = obj.get("dimension_policy")
        if not isinstance(policy, dict) or not obj.get("asset_source"):
            continue
        resolution = obj.get("dimension_resolution")
        if not isinstance(resolution, dict) or not resolution.get("accepted"):
            violations.append(
                {
                    "type": "asset_dimension_resolution_missing_or_rejected",
                    "severity": "hard",
                    "object_id": obj.get("id"),
                }
            )
            continue
        status = str(resolution.get("status") or "unknown")
        mode = str(resolution.get("policy_mode") or policy.get("mode") or "unknown")
        dimension_statuses[status] = dimension_statuses.get(status, 0) + 1
        dimension_policy_modes[mode] = dimension_policy_modes.get(mode, 0) + 1
        effective = resolution.get("effective_dimensions")
        if not isinstance(effective, dict) or any(axis not in effective for axis in AXES):
            violations.append(
                {
                    "type": "asset_dimension_effective_missing",
                    "severity": "hard",
                    "object_id": obj.get("id"),
                }
            )
            continue
        if any(
            abs(float(obj["dimensions"][axis]) - float(effective[axis])) > 1e-5
            for axis in AXES
        ):
            violations.append(
                {
                    "type": "asset_dimensions_changed_after_resolution",
                    "severity": "hard",
                    "object_id": obj.get("id"),
                }
            )
        scale_factors = resolution.get("scale_factors")
        if isinstance(scale_factors, dict) and all(axis in scale_factors for axis in AXES):
            scales = [float(scale_factors[axis]) for axis in AXES]
            max_dimension_scale_anisotropy = max(
                max_dimension_scale_anisotropy, max(scales) - min(scales)
            )
    from .furnishing_groups import evaluate_groups
    violations.extend(evaluate_groups(plan))
    composition_violations, composition_metrics = evaluate_composition(plan)
    violations.extend(composition_violations)
    for obj in objects:
        box = aabb(obj)
        if obj.get("placement_type") != "support" and (
            box[0] < 0.0 or box[1] < 0.0 or box[2] > width or box[3] > length
        ):
            violations.append(
                {"type": "room_boundary", "severity": "hard", "object_id": obj["id"], "aabb": box}
            )
        if obj.get("placement_type") == "floor" and overlap(box, door_box):
            violations.append(
                {"type": "door_clearance", "severity": "hard", "object_id": obj["id"]}
            )
        preferred_wall = obj.get("preferred_wall")
        if obj.get("placement_type") in {"floor", "wall"} and preferred_wall:
            distance = _wall_distance(obj, room, str(preferred_wall))
            if distance > 0.35:
                wall_strength = str(
                    obj.get("wall_constraint_strength")
                    or "hard"
                )
                violations.append(
                    {
                        "type": "wall_affinity",
                        "severity": "hard" if wall_strength == "hard" else "soft",
                        "object_id": obj["id"],
                        "wall": preferred_wall,
                        "distance": round(distance, 4),
                        "constraint_strength": wall_strength,
                    }
                )
        if obj.get("placement_type") == "wall":
            mount_height = float(obj.get("mount_height") or obj.get("z", 0.0))
            if abs(float(obj.get("z", 0.0)) - mount_height) > 0.04:
                violations.append(
                    {
                        "type": "wall_mount_height",
                        "severity": "hard",
                        "object_id": obj["id"],
                        "expected_z": round(mount_height, 4),
                    }
                )
            if float(obj.get("z", 0.0)) < 0.0 or float(obj.get("z", 0.0)) + float(obj["dimensions"]["height"]) > float(room["height"]) + 0.03:
                violations.append(
                    {"type": "wall_vertical_boundary", "severity": "hard", "object_id": obj["id"]}
                )

    for index, left in enumerate(floor_objects):
        for right in floor_objects[index + 1 :]:
            if overlap(aabb(left), aabb(right), margin=0.02):
                violations.append(
                    {
                        "type": "floor_collision",
                        "severity": "hard",
                        "objects": [left["id"], right["id"]],
                    }
                )

    for obj in objects:
        if obj.get("placement_type") != "support":
            continue
        support_id = str(obj.get("support_id") or "")
        support = by_id.get(support_id)
        if not support:
            violations.append(
                {"type": "missing_support", "severity": "hard", "object_id": obj["id"], "support_id": support_id}
            )
            continue
        ox0, oy0, ox1, oy1 = aabb(obj)
        sx0, sy0, sx1, sy1 = aabb(support)
        expected_z = float(support["z"]) + float(support["dimensions"]["height"])
        if ox0 < sx0 - 0.03 or oy0 < sy0 - 0.03 or ox1 > sx1 + 0.03 or oy1 > sy1 + 0.03:
            violations.append(
                {"type": "support_containment", "severity": "hard", "object_id": obj["id"], "support_id": support_id}
            )
        if abs(float(obj.get("z", 0.0)) - expected_z) > 0.04:
            violations.append(
                {
                    "type": "support_height",
                    "severity": "hard",
                    "object_id": obj["id"],
                    "support_id": support_id,
                    "expected_z": round(expected_z, 4),
                }
            )

    support_objects = [obj for obj in objects if obj.get("placement_type") == "support"]
    for index, left in enumerate(support_objects):
        for right in support_objects[index + 1 :]:
            if left.get("support_id") != right.get("support_id"):
                continue
            if overlap(aabb(left), aabb(right), margin=0.01):
                violations.append(
                    {
                        "type": "support_object_collision",
                        "severity": "hard",
                        "objects": [left["id"], right["id"]],
                        "support_id": left.get("support_id"),
                    }
                )

    if not walkway_exists(plan, floor_objects):
        violations.append({"type": "main_walkway", "severity": "hard", "reason": "entry cannot reach room center"})

    room_area = max(0.001, width * length)
    floor_occupancy = sum(footprint(obj)[0] * footprint(obj)[1] for obj in floor_objects) / room_area
    occupancy_min = float(budget.get("floor_occupancy_min", 0.0))
    occupancy_max = float(budget.get("floor_occupancy_max", 1.0))
    if floor_occupancy < occupancy_min:
        violations.append(
            {
                "type": "floor_occupancy_below_target",
                "severity": "soft",
                "floor_occupancy_ratio": round(floor_occupancy, 4),
                "target_min": occupancy_min,
            }
        )
    elif floor_occupancy > occupancy_max:
        violations.append(
            {
                "type": "floor_occupancy_above_target",
                "severity": "soft",
                "floor_occupancy_ratio": round(floor_occupancy, 4),
                "target_max": occupancy_max,
            }
        )

    count_score = 1.0
    if hard_min and len(objects) < hard_min:
        count_score = len(objects) / hard_min
    elif max_auto_inferred and len(auto_inferred) > max_auto_inferred:
        count_score = max_auto_inferred / len(auto_inferred)
    occupancy_score = 1.0
    if occupancy_min and floor_occupancy < occupancy_min:
        occupancy_score = floor_occupancy / occupancy_min
    elif occupancy_max and floor_occupancy > occupancy_max:
        occupancy_score = occupancy_max / floor_occupancy
    compactness_score = max(0.0, min(1.0, (count_score + occupancy_score) / 2.0))
    if len(objects) < hard_min or floor_occupancy < occupancy_min:
        compactness_status = "under_furnished"
    elif floor_occupancy > occupancy_max:
        compactness_status = "over_furnished"
    else:
        compactness_status = "balanced"

    instance_group_violations, instance_group_metrics = validate_instance_groups(
        plan
    )
    violations.extend(instance_group_violations)
    hard = [item for item in violations if item["severity"] == "hard"]
    soft = [item for item in violations if item["severity"] == "soft"]
    constraint_scope_failures = _aggregate_constraint_scope_failures(
        plan, violations
    )
    return {
        "schema": "codex_trellis_layout_validation_v2",
        "ok": not hard,
        "hard_violation_count": len(hard),
        "soft_violation_count": len(soft),
        "violations": violations,
        "constraint_scope_failures": constraint_scope_failures["groups"],
        "metrics": {
            "object_count": len(objects),
            "floor_object_count": len(floor_objects),
            "hard_min_objects": hard_min,
            "target_max_objects": target_max,
            "max_auto_inferred_objects": max_auto_inferred,
            "auto_inferred_object_count": len(auto_inferred),
            "explicit_or_policy_object_count": len(objects) - len(auto_inferred),
            "target_excess_due_to_explicit_or_policy": max(
                0, len(objects) - len(auto_inferred) - target_max
            ),
            "hard_runtime_object_limit": hard_runtime_limit,
            "floor_occupancy_ratio": round(floor_occupancy, 4),
            "floor_occupancy_target": [occupancy_min, occupancy_max],
            "architecture": architecture_metrics,
            "scene_graph": scene_graph_metrics,
            "functional_facing": facing_metrics,
            "spatial_relations": spatial_relation_metrics,
            "constraint_scope_failures": constraint_scope_failures,
            "instance_groups": instance_group_metrics,
            "asset_dimensions": {
                "checked_count": sum(dimension_statuses.values()),
                "status_counts": dimension_statuses,
                "policy_mode_counts": dimension_policy_modes,
                "max_scale_anisotropy": round(max_dimension_scale_anisotropy, 6),
            },
            "composition": composition_metrics,
            "compactness_status": compactness_status,
            "compactness_score": round(compactness_score, 4),
            "walkway_reachable": not any(item["type"] == "main_walkway" for item in violations),
        },
    }
