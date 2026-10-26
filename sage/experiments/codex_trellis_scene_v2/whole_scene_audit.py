from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import numpy as np
import trimesh
from trimesh.transformations import transform_points

from .instance_groups import validate_instance_groups
from .orientation import evaluate_facing, world_front_vector
from .scene_graph import (
    build_typed_scene_graph,
    materialize_scene_graph,
    validate_typed_scene_graph,
)
from .validator import aabb, overlap, validate_layout


SCHEMA = "codex_trellis_whole_scene_regression_audit_v2"
GLB_TRANSFORM_SCHEMA = "codex_trellis_glb_world_transform_audit_v2"
_POSE_TOLERANCE_M = 0.02
_YAW_TOLERANCE_DEGREES = 0.1
_OPERATION_DEPTH_BY_CATEGORY = {
    "wardrobe": 0.65,
    "dresser": 0.55,
    "cabinet": 0.55,
    "bookcase": 0.55,
    "desk": 0.80,
}
_NON_BLOCKING_FLOOR_TYPES = {"floor_covering"}
_NON_BLOCKING_CATEGORIES = {"area_rug", "rug", "carpet"}


def normalize_relation_parent_fields(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Fill absent placement ownership from explicit typed relations.

    Existing non-empty placement fields remain authoritative.  This is intended for
    legacy plans which appended relation-bound objects without updating their
    hierarchy fields.
    """

    by_id = {
        str(item.get("id")): item
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    }
    relation_parent: dict[str, tuple[str, str, str]] = {}
    for relation in plan.get("relations", []):
        if not isinstance(relation, dict):
            continue
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        relation_type = str(relation.get("type") or "")
        if source not in by_id or target not in by_id:
            continue
        if relation_type == "contained_in":
            relation_parent.setdefault(source, ("contained", "container_id", target))
        elif relation_type == "supported_by":
            relation_parent.setdefault(source, ("support", "support_id", target))
    changes: list[dict[str, Any]] = []
    for object_id, obj in by_id.items():
        if str(obj.get("placement_type") or ""):
            continue
        placement_type, parent_field, parent_id = relation_parent.get(
            object_id, ("floor", "", "")
        )
        obj["placement_type"] = placement_type
        if parent_field:
            obj[parent_field] = parent_id
        changes.append(
            {
                "object_id": object_id,
                "placement_type": placement_type,
                "parent_field": parent_field or None,
                "parent_id": parent_id or None,
                "reason": "legacy_missing_placement_recovered_from_typed_relation"
                if parent_field
                else "legacy_missing_placement_recovered_as_floor_object",
            }
        )
    return changes


def refresh_typed_scene_graph(plan: dict[str, Any]) -> dict[str, Any]:
    """Recompile and materialize the graph after objects or relations change."""

    architecture = plan.get("architecture")
    architecture_plan = {
        "architecture": architecture if isinstance(architecture, dict) else {}
    }
    graph = build_typed_scene_graph(plan, architecture_plan)
    graph = materialize_scene_graph(graph, plan.get("objects", []))
    plan["scene_graph"] = graph
    return graph


def _typed_graph_audit(plan: dict[str, Any]) -> dict[str, Any]:
    graph = plan.get("scene_graph")
    if not isinstance(graph, dict):
        return {
            "ok": False,
            "validation": {"ok": False, "errors": ["typed scene graph missing"]},
            "missing_object_node_ids": sorted(
                str(item.get("id"))
                for item in plan.get("objects", [])
                if isinstance(item, dict) and item.get("id")
            ),
        }
    validation = validate_typed_scene_graph(graph)
    nodes = [item for item in graph.get("nodes", []) if isinstance(item, dict)]
    object_nodes = {
        str(item.get("id"))
        for item in nodes
        if str(item.get("node_kind")) == "object"
    }
    expected_objects = {
        str(item.get("id"))
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    }
    opening_nodes = {
        str(item.get("id"))
        for item in nodes
        if str(item.get("node_kind")) == "architectural_opening"
    }
    architecture = plan.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    expected_openings = {
        str(item.get("id"))
        for collection in ("doors", "windows")
        for item in architecture.get(collection, [])
        if isinstance(item, dict) and item.get("id")
    }
    relation_keys = {
        (
            str(item.get("source")),
            str(item.get("type")),
            str(item.get("target")),
        )
        for item in graph.get("relations", [])
        if isinstance(item, dict)
    }
    expected_hard_relations = {
        (
            str(item.get("source")),
            str(item.get("type")),
            str(item.get("target")),
        )
        for item in plan.get("relations", [])
        if isinstance(item, dict) and str(item.get("strength") or "soft") == "hard"
    }
    missing_hard_relations = sorted(expected_hard_relations - relation_keys)
    node_by_id = {str(item.get("id")): item for item in nodes}
    support_parent_failures: list[dict[str, Any]] = []
    pose_failures: list[dict[str, Any]] = []
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        object_id = str(obj["id"])
        node = node_by_id.get(object_id)
        if node is None:
            continue
        support_id = str(obj.get("support_id") or "")
        if support_id and str(node.get("parent_id") or "") != support_id:
            support_parent_failures.append(
                {
                    "object_id": object_id,
                    "expected_parent_id": support_id,
                    "actual_parent_id": node.get("parent_id"),
                }
            )
        pose = node.get("pose")
        world_pose = pose.get("world") if isinstance(pose, dict) else None
        if not isinstance(world_pose, dict):
            pose_failures.append({"object_id": object_id, "reason": "world_pose_missing"})
            continue
        residuals = {
            key: abs(float(world_pose.get(key, 0.0)) - float(obj.get(key, 0.0)))
            for key in ("x", "y", "z")
        }
        yaw_error = abs(
            (float(world_pose.get("yaw", 0.0)) - float(obj.get("yaw", 0.0)) + 180.0)
            % 360.0
            - 180.0
        )
        if max(residuals.values(), default=0.0) > 1e-6 or yaw_error > 1e-6:
            pose_failures.append(
                {
                    "object_id": object_id,
                    "position_residuals": residuals,
                    "yaw_error_degrees": yaw_error,
                }
            )
    plan_groups = {
        str(item.get("group_id"))
        for item in plan.get("instance_groups", [])
        if isinstance(item, dict) and item.get("group_id")
    }
    graph_groups = {
        str(item.get("group_id"))
        for item in graph.get("instance_groups", [])
        if isinstance(item, dict) and item.get("group_id")
    }
    result = {
        "validation": validation,
        "expected_object_node_count": len(expected_objects),
        "actual_object_node_count": len(object_nodes),
        "missing_object_node_ids": sorted(expected_objects - object_nodes),
        "unexpected_object_node_ids": sorted(object_nodes - expected_objects),
        "expected_opening_node_count": len(expected_openings),
        "actual_opening_node_count": len(opening_nodes),
        "missing_opening_node_ids": sorted(expected_openings - opening_nodes),
        "unexpected_opening_node_ids": sorted(opening_nodes - expected_openings),
        "missing_hard_relations": [list(item) for item in missing_hard_relations],
        "missing_instance_group_ids": sorted(plan_groups - graph_groups),
        "unexpected_instance_group_ids": sorted(graph_groups - plan_groups),
        "support_parent_failures": support_parent_failures,
        "materialized_pose_failures": pose_failures,
    }
    result["ok"] = bool(
        validation.get("ok")
        and not result["missing_object_node_ids"]
        and not result["unexpected_object_node_ids"]
        and not result["missing_opening_node_ids"]
        and not result["unexpected_opening_node_ids"]
        and not missing_hard_relations
        and not result["missing_instance_group_ids"]
        and not result["unexpected_instance_group_ids"]
        and not support_parent_failures
        and not pose_failures
    )
    return result


def _vertical_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_bottom = float(left.get("z", 0.0))
    right_bottom = float(right.get("z", 0.0))
    left_top = left_bottom + float(left["dimensions"]["height"])
    right_top = right_bottom + float(right["dimensions"]["height"])
    return not (left_top + 0.02 <= right_bottom or right_top + 0.02 <= left_bottom)


def _intentional_overlap_pairs(plan: dict[str, Any]) -> set[frozenset[str]]:
    accepted_types = {"contained_in", "supported_by", "tucked_under"}
    return {
        frozenset((str(item.get("source")), str(item.get("target"))))
        for item in plan.get("relations", [])
        if isinstance(item, dict) and str(item.get("type")) in accepted_types
    }


def _layout_gate(plan: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    report = validate_layout(plan)
    by_id = {
        str(item.get("id")): item
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    }
    intentional_pairs = _intentional_overlap_pairs(plan)
    ignored_broad_phase: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for violation in report.get("violations", []):
        if str(violation.get("severity")) != "hard":
            continue
        if str(violation.get("type")) != "floor_collision":
            failures.append(deepcopy(violation))
            continue
        pair_ids = [str(value) for value in violation.get("objects", [])]
        pair = frozenset(pair_ids)
        left = by_id.get(pair_ids[0]) if len(pair_ids) == 2 else None
        right = by_id.get(pair_ids[1]) if len(pair_ids) == 2 else None
        thin_floor_layer = bool(
            left is not None
            and right is not None
            and (
                str(left.get("category") or "") in _NON_BLOCKING_CATEGORIES
                or str(right.get("category") or "") in _NON_BLOCKING_CATEGORIES
                or str(left.get("placement_type") or "") in _NON_BLOCKING_FLOOR_TYPES
                or str(right.get("placement_type") or "") in _NON_BLOCKING_FLOOR_TYPES
            )
        )
        if pair in intentional_pairs or thin_floor_layer or (
            left is not None and right is not None and not _vertical_overlap(left, right)
        ):
            ignored_broad_phase.append(deepcopy(violation))
        else:
            failures.append(deepcopy(violation))
    return report, {
        "ok": not failures,
        "failure_count": len(failures),
        "failures": failures,
        "ignored_relation_or_vertical_broad_phase_count": len(ignored_broad_phase),
        "ignored_relation_or_vertical_broad_phase": ignored_broad_phase,
    }


def _front_clearance_box(
    obj: dict[str, Any], *, direction: tuple[float, float], depth: float, margin: float
) -> tuple[float, float, float, float] | None:
    x0, y0, x1, y1 = aabb(obj)
    dx, dy = direction
    if abs(dx) >= 0.999 and abs(dy) <= 0.001:
        return (x1, y0 - margin, x1 + depth, y1 + margin) if dx > 0 else (
            x0 - depth,
            y0 - margin,
            x0,
            y1 + margin,
        )
    if abs(dy) >= 0.999 and abs(dx) <= 0.001:
        return (x0 - margin, y1, x1 + margin, y1 + depth) if dy > 0 else (
            x0 - margin,
            y0 - depth,
            x1 + margin,
            y0,
        )
    return None


def _operation_clearance_audit(plan: dict[str, Any]) -> dict[str, Any]:
    objects = [item for item in plan.get("objects", []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in objects if item.get("id")}
    blockers = [
        item
        for item in objects
        if str(item.get("placement_type") or "floor") == "floor"
        and str(item.get("category") or "") not in _NON_BLOCKING_CATEGORIES
        and str(item.get("placement_type") or "") not in _NON_BLOCKING_FLOOR_TYPES
    ]
    tucked_by_target: dict[str, set[str]] = {}
    tucked_relations: list[dict[str, Any]] = []
    for relation in plan.get("relations", []):
        if not isinstance(relation, dict) or str(relation.get("type")) != "tucked_under":
            continue
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        if source and target:
            tucked_by_target.setdefault(target, set()).add(source)
            tucked_relations.append(relation)

    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    width = float(room.get("width", 0.0))
    length = float(room.get("length", 0.0))
    results: list[dict[str, Any]] = []

    def evaluate_zone(
        *,
        zone_id: str,
        owner_id: str,
        box: tuple[float, float, float, float] | None,
        allowed_ids: set[str],
    ) -> None:
        if box is None:
            results.append(
                {
                    "zone_id": zone_id,
                    "owner_id": owner_id,
                    "ok": False,
                    "reason": "non_cardinal_operation_direction",
                    "blocking_object_ids": [],
                }
            )
            return
        outside_room = box[0] < -1e-6 or box[1] < -1e-6 or box[2] > width + 1e-6 or box[3] > length + 1e-6
        blocking_ids = sorted(
            str(item.get("id"))
            for item in blockers
            if str(item.get("id")) not in allowed_ids
            and str(item.get("id")) != owner_id
            and overlap(box, aabb(item))
        )
        results.append(
            {
                "zone_id": zone_id,
                "owner_id": owner_id,
                "box": [round(float(value), 6) for value in box],
                "allowed_object_ids": sorted(allowed_ids),
                "blocking_object_ids": blocking_ids,
                "outside_room": outside_room,
                "ok": not blocking_ids and not outside_room,
            }
        )

    for obj in objects:
        object_id = str(obj.get("id") or "")
        category = str(obj.get("category") or "")
        facing = obj.get("facing_constraint")
        facing = facing if isinstance(facing, dict) else {}
        depth = float(
            obj.get(
                "operation_clearance_depth",
                facing.get(
                    "front_clearance_depth",
                    _OPERATION_DEPTH_BY_CATEGORY.get(category, 0.0),
                ),
            )
            or 0.0
        )
        if depth <= 0.0 or not isinstance(obj.get("facing_constraint"), dict):
            continue
        direction = world_front_vector(obj)
        evaluate_zone(
            zone_id=f"front_access:{object_id}",
            owner_id=object_id,
            box=_front_clearance_box(obj, direction=direction, depth=depth, margin=0.05),
            allowed_ids=tucked_by_target.get(object_id, set()),
        )

    for relation in tucked_relations:
        chair_id = str(relation.get("source"))
        target_id = str(relation.get("target"))
        chair = by_id.get(chair_id)
        target = by_id.get(target_id)
        if chair is None or target is None:
            results.append(
                {
                    "zone_id": f"pullout:{chair_id}",
                    "owner_id": chair_id,
                    "ok": False,
                    "reason": "tucked_relation_endpoint_missing",
                    "blocking_object_ids": [],
                }
            )
            continue
        parameters = relation.get("parameters")
        parameters = parameters if isinstance(parameters, dict) else {}
        pullout_depth = float(parameters.get("pullout_clearance_depth", 0.35) or 0.35)
        evaluate_zone(
            zone_id=f"pullout:{chair_id}",
            owner_id=chair_id,
            box=_front_clearance_box(
                chair,
                direction=world_front_vector(target),
                depth=pullout_depth,
                margin=0.0,
            ),
            allowed_ids={target_id},
        )

    failures = [item for item in results if not item["ok"]]
    return {
        "ok": not failures,
        "checked_count": len(results),
        "failure_count": len(failures),
        "results": results,
    }


def audit_plan(
    plan: dict[str, Any], relation_audit: dict[str, Any] | None = None
) -> dict[str, Any]:
    objects = [
        item
        for item in plan.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    ]
    object_ids = {str(item["id"]) for item in objects}
    budget = plan.get("object_budget")
    budget = budget if isinstance(budget, dict) else {}
    required_ids = {
        str(value) for value in budget.get("required_object_ids", []) if str(value)
    }
    missing_required = sorted(required_ids - object_ids)
    group_violations, group_metrics = validate_instance_groups(plan)
    declared_group_ids = {
        str(item.get("group_id"))
        for item in plan.get("instance_groups", [])
        if isinstance(item, dict) and item.get("group_id")
    }
    orphan_group_members = [
        {
            "object_id": str(item.get("id")),
            "instance_group_id": str(item.get("instance_group_id")),
        }
        for item in objects
        if item.get("instance_group_id")
        and str(item.get("instance_group_id")) not in declared_group_ids
    ]
    group_metrics = deepcopy(group_metrics)
    group_metrics["orphan_member_count"] = len(orphan_group_members)
    group_metrics["orphan_members"] = orphan_group_members
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    facing_results = [
        result
        for obj in objects
        if (result := evaluate_facing(obj, room)) is not None
    ]
    facing_failures = [item for item in facing_results if not bool(item["ok"])]
    graph_audit = _typed_graph_audit(plan)
    validator_report, layout_gate = _layout_gate(plan)
    operation_clearance = _operation_clearance_audit(plan)
    support_failure_types = {
        "missing_support",
        "support_containment",
        "support_height",
        "support_object_collision",
    }
    support_failures = [
        deepcopy(item)
        for item in validator_report.get("violations", [])
        if str(item.get("type")) in support_failure_types
        and str(item.get("severity")) == "hard"
    ]
    opening_failures = [
        deepcopy(item)
        for item in validator_report.get("violations", [])
        if str(item.get("severity")) == "hard"
        and (
            str(item.get("type")).startswith("architecture_")
            or str(item.get("type")) in {"window_obstruction", "door_clearance", "main_walkway"}
        )
    ]
    relation_required = relation_audit is not None
    relation_ok = bool(relation_audit and relation_audit.get("ok")) if relation_required else None
    target_feature_ok = bool(not relation_required or relation_ok)
    whole_scene_ok = bool(
        not missing_required
        and not any(item.get("severity") == "hard" for item in group_violations)
        and not orphan_group_members
        and not facing_failures
        and graph_audit["ok"]
        and layout_gate["ok"]
        and not support_failures
        and not opening_failures
        and operation_clearance["ok"]
        and target_feature_ok
    )
    return {
        "schema": SCHEMA,
        "ok": whole_scene_ok,
        "target_feature_ok": target_feature_ok,
        "whole_scene_ok": whole_scene_ok,
        "required_object_count": len(required_ids),
        "missing_required_object_ids": missing_required,
        "typed_scene_graph": graph_audit,
        "instance_groups": group_metrics,
        "instance_group_violations": group_violations,
        "functional_facing": {
            "evaluated_count": len(facing_results),
            "failure_count": len(facing_failures),
            "results": facing_results,
        },
        "support_parent": {
            "evaluated_count": sum(
                1 for item in objects if str(item.get("placement_type")) == "support"
            ),
            "failure_count": len(support_failures),
            "failures": support_failures,
        },
        "architecture_openings_and_entry": {
            "metrics": deepcopy(validator_report.get("metrics", {}).get("architecture", {})),
            "failure_count": len(opening_failures),
            "failures": opening_failures,
            "walkway_reachable": bool(
                validator_report.get("metrics", {}).get("walkway_reachable")
            ),
        },
        "operation_clearance": operation_clearance,
        "layout_non_regression_gate": layout_gate,
        "relation_geometry_required": relation_required,
        "relation_geometry_ok": relation_ok,
        "glb_world_transforms_required": False,
        "glb_world_transforms": None,
    }


def _geometry_world_bounds(
    scene: trimesh.Scene, nodes: list[str], frame: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    transformed: list[np.ndarray] = []
    for node in nodes:
        matrix, geometry_name = scene.graph.get(node)
        if geometry_name is None:
            continue
        transformed.append(
            transform_points(scene.geometry[geometry_name].vertices, matrix if frame is None else frame @ matrix)
        )
    if not transformed:
        raise ValueError("no geometry bounds")
    points = np.vstack(transformed)
    return points.min(axis=0), points.max(axis=0)


def audit_glb_world_transforms(
    plan: dict[str, Any], scene: trimesh.Scene
) -> dict[str, Any]:
    geometry_nodes = [str(value) for value in scene.graph.nodes_geometry]
    graph_nodes = {str(value) for value in scene.graph.nodes}
    results: list[dict[str, Any]] = []
    for obj in plan.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        object_id = str(obj["id"])
        matching = sorted(
            node
            for node in geometry_nodes
            if node.startswith(f"{object_id}_geometry_")
        )
        root_node = f"{object_id}_root"
        if not matching or root_node not in graph_nodes:
            results.append(
                {
                    "object_id": object_id,
                    "ok": False,
                    "missing_geometry": not matching,
                    "missing_root_transform": root_node not in graph_nodes,
                }
            )
            continue
        dims = obj["dimensions"]
        expected_yaw = (float(obj.get("yaw", 0.0)) + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)) % 360.0
        angle = math.radians(expected_yaw)
        gltf_to_z = np.array([[1,0,0,0],[0,0,-1,0],[0,1,0,0],[0,0,0,1]], dtype=float)
        undo_yaw = np.array([[math.cos(angle),math.sin(angle),0,0],[-math.sin(angle),math.cos(angle),0,0],[0,0,1,0],[0,0,0,1]], dtype=float)
        frame = undo_yaw @ gltf_to_z
        expected_extents = np.array([float(dims[key]) for key in ("width", "length", "height")])
        expected_center = (undo_yaw @ np.array([float(obj.get("x",0)),float(obj.get("y",0)),float(obj.get("z",0))+expected_extents[2]/2,1]))[:3]
        if obj.get("rigid_body_pose_matrix_z_up") is not None:
            frame = np.linalg.inv(np.asarray(obj["rigid_body_pose_matrix_z_up"],dtype=float)) @ gltf_to_z
            expected_center = np.zeros(3)
        minimum, maximum = _geometry_world_bounds(scene, matching, frame=frame)
        actual_center = (minimum + maximum) * 0.5
        actual_extents = maximum - minimum
        center_error = float(np.max(np.abs(actual_center - expected_center)))
        extent_error = float(np.max(np.abs(actual_extents - expected_extents)))
        extent_tolerance = max(2e-5, float(expected_extents.max()) * 1e-5)
        root_matrix, _ = scene.graph.get(root_node)
        determinant = float(np.linalg.det(np.asarray(root_matrix[:3, :3], dtype=np.float64)))
        actual_yaw = math.degrees(
            math.atan2(float(-root_matrix[2, 0]), float(root_matrix[0, 0]))
        ) % 360.0
        expected_yaw = (
            float(obj.get("yaw", 0.0))
            + float(obj.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
        ) % 360.0
        yaw_error = abs((actual_yaw - expected_yaw + 180.0) % 360.0 - 180.0)
        results.append(
            {
                "object_id": object_id,
                "geometry_node_count": len(matching),
                "bounds_method": "actual_vertices_in_placement_frame",
                "actual_dimensions_m": actual_extents.tolist(),
                "expected_dimensions_m": expected_extents.tolist(),
                "extent_tolerance_m": extent_tolerance,
                "center_max_error_m": round(center_error, 6),
                "extent_max_error_m": round(extent_error, 6),
                "expected_yaw_degrees": round(expected_yaw, 6),
                "actual_yaw_degrees": round(actual_yaw, 6),
                "yaw_error_degrees": round(yaw_error, 6),
                "root_determinant": determinant,
                "positive_determinant": determinant > 0.0,
                "ok": bool(
                    center_error <= _POSE_TOLERANCE_M
                    and extent_error <= extent_tolerance
                    and yaw_error <= _YAW_TOLERANCE_DEGREES
                    and determinant > 0.0
                ),
            }
        )
    architecture = plan.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}
    opening_ids = [
        str(item.get("id"))
        for collection in ("doors", "windows")
        for item in architecture.get(collection, [])
        if isinstance(item, dict) and item.get("id")
    ]
    missing_opening_geometry_ids = sorted(
        opening_id
        for opening_id in opening_ids
        if not any(node.startswith(f"{opening_id}_geometry_") for node in geometry_nodes)
    )
    failures = [item for item in results if not item["ok"]]
    return {
        "schema": GLB_TRANSFORM_SCHEMA,
        "ok": not failures and not missing_opening_geometry_ids,
        "object_count": len(results),
        "accepted_object_count": len(results) - len(failures),
        "failure_count": len(failures),
        "missing_opening_geometry_ids": missing_opening_geometry_ids,
        "results": results,
    }


def attach_glb_audit(
    plan_audit: dict[str, Any], glb_audit: dict[str, Any]
) -> dict[str, Any]:
    result = deepcopy(plan_audit)
    result["glb_world_transforms_required"] = True
    result["glb_world_transforms"] = deepcopy(glb_audit)
    result["whole_scene_ok"] = bool(result.get("whole_scene_ok") and glb_audit.get("ok"))
    result["ok"] = bool(result["whole_scene_ok"] and result.get("target_feature_ok"))
    return result
