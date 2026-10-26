from __future__ import annotations

import math
from collections import Counter, deque
from copy import deepcopy
from typing import Any, Iterable


SCENE_GRAPH_SCHEMA = "codex_trellis_typed_scene_graph_v1"


RELATION_VOCABULARY: dict[str, dict[str, Any]] = {
    "part_of": {
        "constraint_class": "composition",
        "default_strength": "hard",
        "directed": True,
    },
    "contained_in": {
        "constraint_class": "containment",
        "default_strength": "hard",
        "directed": True,
    },
    "installed_in": {
        "constraint_class": "structural",
        "default_strength": "hard",
        "directed": True,
    },
    "attached_to": {
        "constraint_class": "attachment",
        "default_strength": "hard",
        "directed": True,
    },
    "supported_by": {
        "constraint_class": "support",
        "default_strength": "hard",
        "directed": True,
    },
    "tucked_under": {
        "constraint_class": "free_space",
        "default_strength": "hard",
        "directed": True,
    },
    "partially_inserted": {
        "constraint_class": "free_space",
        "default_strength": "hard",
        "directed": True,
    },
    "contact": {
        "constraint_class": "contact",
        "default_strength": "hard",
        "directed": True,
    },
    "against_wall": {
        "constraint_class": "contact",
        "default_strength": "hard",
        "directed": True,
    },
    "faces": {
        "constraint_class": "functional",
        "default_strength": "soft",
        "directed": True,
    },
    "faces_accessible_space": {
        "constraint_class": "functional",
        "default_strength": "hard",
        "directed": True,
    },
    "left_of": {
        "constraint_class": "spatial",
        "default_strength": "soft",
        "directed": True,
    },
    "right_of": {
        "constraint_class": "spatial",
        "default_strength": "soft",
        "directed": True,
    },
    "aligned_with": {
        "constraint_class": "alignment",
        "default_strength": "soft",
        "directed": True,
    },
    "mirror_symmetric": {
        "constraint_class": "alignment",
        "default_strength": "soft",
        "directed": False,
    },
    "in_front_of": {
        "constraint_class": "spatial",
        "default_strength": "soft",
        "directed": True,
    },
    "above": {
        "constraint_class": "spatial",
        "default_strength": "soft",
        "directed": True,
    },
    "separated_from": {
        "constraint_class": "clearance",
        "default_strength": "soft",
        "directed": False,
    },
    "work_triangle": {
        "constraint_class": "functional",
        "default_strength": "soft",
        "directed": False,
    },
    "clearance_from": {
        "constraint_class": "clearance",
        "default_strength": "hard",
        "directed": True,
    },
    "included_by_asset": {
        "constraint_class": "composition",
        "default_strength": "hard",
        "directed": True,
    },
}


LEGACY_RELATION_ALIASES = {
    "against": "against_wall",
    "on": "supported_by",
    "inside": "contained_in",
}


def _node(
    node_id: str,
    *,
    node_kind: str,
    semantic_type: str,
    parent_id: str | None,
    parent_relation: str | None,
    transform_space: str,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "node_kind": node_kind,
        "semantic_type": semantic_type,
        "parent_id": parent_id,
        "parent_relation": parent_relation,
        "transform_space": transform_space,
        "source": deepcopy(source or {}),
    }


def _object_source(obj: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "id",
        "category",
        "required",
        "provenance",
        "placement_type",
        "window_treatment",
        "furnishing_anchor_id",
        "furnishing_attachment",
        "part_of_id",
        "container_id",
        "container_slot",
        "support_id",
        "support_offset",
        "preferred_wall",
        "wall_constraint_strength",
        "wall_constraint_provenance",
        "mount_height",
        "dimensions",
        "requested_dimensions",
        "dimension_policy",
        "dimension_resolution",
        "asset_id",
        "asset_source",
        "staged_asset",
        "asset_canonical_front",
        "asset_orientation",
        "asset_affordance",
        "usage_constraints",
        "included_components",
        "component_policy",
        "component_requirements",
        "support_surfaces",
        "containment_volumes",
        "free_space_volumes",
        "facing_constraint",
    )
    return {key: deepcopy(obj[key]) for key in keys if key in obj}


def _relation(
    source: str,
    relation_type: str,
    target: str,
    *,
    provenance: str,
    strength: str | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = RELATION_VOCABULARY.get(
        relation_type,
        {
            "constraint_class": "semantic",
            "default_strength": "soft",
            "directed": True,
        },
    )
    return {
        "id": f"relation:{source}:{relation_type}:{target}",
        "source": source,
        "type": relation_type,
        "target": target,
        "constraint_class": str(spec["constraint_class"]),
        "strength": strength or str(spec["default_strength"]),
        "directed": bool(spec["directed"]),
        "provenance": [provenance],
        "parameters": deepcopy(parameters or {}),
    }


def _merge_relation(
    relations: dict[tuple[str, str, str], dict[str, Any]], edge: dict[str, Any]
) -> None:
    key = (str(edge["source"]), str(edge["type"]), str(edge["target"]))
    existing = relations.get(key)
    if not existing:
        relations[key] = edge
        return
    existing_sources = existing.setdefault("provenance", [])
    for source in edge.get("provenance", []):
        if source not in existing_sources:
            existing_sources.append(source)
    if edge.get("strength") == "hard":
        existing["strength"] = "hard"
    existing.setdefault("parameters", {}).update(deepcopy(edge.get("parameters", {})))


def _wall_node_id(wall: Any) -> str:
    value = str(wall or "").strip().lower()
    return f"{value}_wall" if value else ""


def _primary_parent(
    obj: dict[str, Any], node_ids: set[str]
) -> tuple[str, str, str]:
    placement_type = str(obj.get("placement_type") or "floor")
    window_id = obj.get("window_treatment", {}).get("window_id")
    if window_id in node_ids:
        return window_id, "attached_to", "parent_local"
    part_of_id = str(obj.get("part_of_id") or "")
    if part_of_id:
        return part_of_id, "part_of", "parent_local"
    container_id = str(obj.get("container_id") or "")
    if container_id:
        return container_id, "contained_in", "parent_local"
    support_id = str(obj.get("support_id") or "")
    if support_id:
        return support_id, "supported_by", "parent_local"
    if placement_type == "wall":
        wall_id = _wall_node_id(obj.get("preferred_wall"))
        if wall_id in node_ids:
            return wall_id, "attached_to", "parent_local"
    if placement_type == "floor_covering" and "floor" in node_ids:
        return "floor", "supported_by", "parent_local"
    return "room", "contained_in", "room_world"


def _legacy_relations(raw_relations: Iterable[Any]) -> Iterable[dict[str, Any]]:
    for item in raw_relations:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            source, raw_type, target = (str(value) for value in item)
            relation_type = LEGACY_RELATION_ALIASES.get(raw_type, raw_type)
            yield _relation(
                source,
                relation_type,
                target,
                provenance="room_policy_relation",
            )
        elif isinstance(item, dict):
            source = str(item.get("source") or item.get("subject") or "")
            target = str(item.get("target") or item.get("object") or "")
            raw_type = str(item.get("type") or item.get("predicate") or "")
            if not source or not target or not raw_type:
                continue
            relation_type = LEGACY_RELATION_ALIASES.get(raw_type, raw_type)
            yield _relation(
                source,
                relation_type,
                target,
                provenance=str(item.get("provenance") or "structured_relation"),
                strength=str(item.get("strength") or "") or None,
                parameters=item.get("parameters") if isinstance(item.get("parameters"), dict) else None,
            )


def validate_typed_scene_graph(graph: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    node_ids = [str(node.get("id") or "") for node in nodes if isinstance(node, dict)]
    known = set(node_ids)
    duplicates = sorted(node_id for node_id, count in Counter(node_ids).items() if count > 1)
    if duplicates:
        errors.append("duplicate node ids: " + ", ".join(duplicates))
    root_id = str(graph.get("root_id") or "")
    if root_id not in known:
        errors.append(f"missing root node: {root_id}")

    parent_by_id: dict[str, str] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        parent_id = str(node.get("parent_id") or "")
        if node_id == root_id:
            if parent_id:
                errors.append(f"root node {root_id} cannot have parent {parent_id}")
            continue
        if not parent_id:
            errors.append(f"node {node_id} has no primary parent")
        elif parent_id not in known:
            errors.append(f"node {node_id} references missing parent {parent_id}")
        else:
            parent_by_id[node_id] = parent_id

    for start in parent_by_id:
        seen: set[str] = set()
        current = start
        while current in parent_by_id:
            if current in seen:
                errors.append(f"primary hierarchy cycle includes {current}")
                break
            seen.add(current)
            current = parent_by_id[current]

    for edge in graph.get("relations", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in known:
            errors.append(f"relation {edge.get('id')} has missing source {source}")
        if target not in known:
            errors.append(f"relation {edge.get('id')} has missing target {target}")
        if str(edge.get("type") or "") == "tucked_under":
            parameters = edge.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            if not str(parameters.get("free_space_id") or ""):
                errors.append(
                    f"relation {edge.get('id')} requires parameters.free_space_id"
                )
            if parameters.get("reference_frame") != "target_local":
                errors.append(
                    f"relation {edge.get('id')} requires target_local reference frame"
                )
            if edge.get("strength") != "hard":
                errors.append(
                    f"relation {edge.get('id')} must be a hard constraint"
                )
        if str(edge.get("type") or "") == "mirror_symmetric":
            parameters = edge.get("parameters")
            parameters = parameters if isinstance(parameters, dict) else {}
            reference_id = str(parameters.get("reference_id") or "")
            if reference_id not in known:
                errors.append(
                    f"relation {edge.get('id')} has missing mirror reference {reference_id}"
                )

    relation_ids = {
        str(edge.get("id") or "")
        for edge in graph.get("relations", [])
        if isinstance(edge, dict)
    }
    scope_ids: set[str] = set()
    for scope in graph.get("constraint_scopes", []):
        if not isinstance(scope, dict):
            errors.append("constraint scope must be an object")
            continue
        scope_id = str(scope.get("scope_id") or "")
        if scope_id in scope_ids:
            errors.append(f"duplicate constraint scope id: {scope_id}")
        scope_ids.add(scope_id)
        for member in scope.get("members", []):
            object_id = str(member.get("object_id") or "") if isinstance(member, dict) else ""
            if object_id not in known:
                errors.append(f"constraint scope {scope_id} has missing member {object_id}")
        for ref in scope.get("relation_refs", []):
            ref_id = str(ref.get("id") or "") if isinstance(ref, dict) else ""
            if ref_id not in relation_ids:
                errors.append(f"constraint scope {scope_id} has missing relation {ref_id}")

    group_ids: set[str] = set()
    rigid_memberships: dict[str, str] = {}
    for group in graph.get("instance_groups", []):
        if not isinstance(group, dict):
            errors.append("instance group must be an object")
            continue
        group_id = str(group.get("group_id") or "")
        if group_id in group_ids:
            errors.append(f"duplicate instance group id: {group_id}")
        group_ids.add(group_id)
        members = [
            member
            for member in group.get("members", [])
            if isinstance(member, dict)
        ]
        if int(group.get("cardinality", 0) or 0) != len(members):
            errors.append(f"instance group {group_id} has invalid cardinality")
        for member in members:
            object_id = str(member.get("object_id") or "")
            if object_id not in known:
                errors.append(f"instance group {group_id} has missing member {object_id}")
            if object_id in rigid_memberships:
                errors.append(
                    f"instance group member {object_id} overlaps "
                    f"{rigid_memberships[object_id]} and {group_id}"
                )
            else:
                rigid_memberships[object_id] = group_id

    return {"ok": not errors, "error_count": len(errors), "errors": errors}


def _hierarchy_metadata(nodes: list[dict[str, Any]], root_id: str) -> dict[str, Any]:
    children: dict[str, list[str]] = {str(node["id"]): [] for node in nodes}
    for node in nodes:
        parent_id = node.get("parent_id")
        if parent_id in children:
            children[str(parent_id)].append(str(node["id"]))
    for value in children.values():
        value.sort()

    traversal: list[str] = []
    depth_by_node: dict[str, int] = {root_id: 0}
    queue: deque[str] = deque([root_id])
    while queue:
        node_id = queue.popleft()
        traversal.append(node_id)
        for child_id in children.get(node_id, []):
            depth_by_node[child_id] = depth_by_node[node_id] + 1
            queue.append(child_id)
    return {
        "children_by_node": children,
        "breadth_first_order": traversal,
        "depth_by_node": depth_by_node,
        "max_depth": max(depth_by_node.values(), default=0),
    }


def build_typed_scene_graph(
    brief: dict[str, Any], architecture_plan: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compile one primary ownership tree plus typed cross-node relations.

    The graph is semantic and asset-aware, but geometry-neutral. A later layout pass
    calls ``materialize_scene_graph`` to attach world and parent-local poses.
    """

    architecture_source = architecture_plan or {}
    architecture = architecture_source.get("architecture")
    if not isinstance(architecture, dict):
        architecture = brief.get("architecture")
    architecture = architecture if isinstance(architecture, dict) else {}

    room_source = deepcopy(brief.get("room") or {})
    room_source["room_type"] = brief.get("room_type")
    nodes: list[dict[str, Any]] = [
        _node(
            "room",
            node_kind="room",
            semantic_type=str(brief.get("room_type") or "room"),
            parent_id=None,
            parent_relation=None,
            transform_space="world",
            source=room_source,
        )
    ]

    wall_names = [str(wall) for wall in architecture.get("walls", [])]
    for wall in wall_names:
        nodes.append(
            _node(
                _wall_node_id(wall),
                node_kind="structure",
                semantic_type="wall",
                parent_id="room",
                parent_relation="contained_in",
                transform_space="room_world",
                source={"wall": wall},
            )
        )

    floor = architecture.get("floor")
    if isinstance(floor, dict):
        floor_id = str(floor.get("id") or "floor")
        nodes.append(
            _node(
                floor_id,
                node_kind="structure",
                semantic_type="floor",
                parent_id="room",
                parent_relation="contained_in",
                transform_space="room_world",
                source=floor,
            )
        )

    known_node_ids = {str(node["id"]) for node in nodes}
    for opening_type in ("doors", "windows"):
        semantic_type = "door" if opening_type == "doors" else "window"
        for opening in architecture.get(opening_type, []):
            if not isinstance(opening, dict):
                continue
            opening_id = str(opening.get("id") or f"{semantic_type}_{len(nodes)}")
            wall_id = _wall_node_id(opening.get("wall"))
            parent_id = wall_id if wall_id in known_node_ids else "room"
            nodes.append(
                _node(
                    opening_id,
                    node_kind="architectural_opening",
                    semantic_type=semantic_type,
                    parent_id=parent_id,
                    parent_relation="installed_in",
                    transform_space="parent_local",
                    source=opening,
                )
            )
            known_node_ids.add(opening_id)

    objects = [obj for obj in brief.get("objects", []) if isinstance(obj, dict)]
    known_node_ids.update(str(obj.get("id")) for obj in objects if obj.get("id"))
    for obj in objects:
        object_id = str(obj["id"])
        parent_id, parent_relation, transform_space = _primary_parent(obj, known_node_ids)
        nodes.append(
            _node(
                object_id,
                node_kind="object",
                semantic_type=str(obj.get("category") or "object"),
                parent_id=parent_id,
                parent_relation=parent_relation,
                transform_space=transform_space,
                source=_object_source(obj),
            )
        )

    known_node_ids = {str(node["id"]) for node in nodes}
    relation_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for node in nodes:
        node_id = str(node["id"])
        parent_id = node.get("parent_id")
        parent_relation = node.get("parent_relation")
        if parent_id and parent_relation:
            _merge_relation(
                relation_index,
                _relation(
                    node_id,
                    str(parent_relation),
                    str(parent_id),
                    provenance="primary_hierarchy",
                ),
            )

    for obj in objects:
        object_id = str(obj["id"])
        placement_type = str(obj.get("placement_type") or "floor")
        if placement_type == "floor" and "floor" in known_node_ids:
            _merge_relation(
                relation_index,
                _relation(
                    object_id,
                    "supported_by",
                    "floor",
                    provenance="placement_type",
                ),
            )
        preferred_wall = _wall_node_id(obj.get("preferred_wall"))
        if preferred_wall in known_node_ids:
            _merge_relation(
                relation_index,
                _relation(
                    object_id,
                    "against_wall",
                    preferred_wall,
                    provenance="preferred_wall",
                    strength=str(obj.get("wall_constraint_strength") or "soft"),
                ),
            )
        facing = obj.get("facing_constraint")
        if isinstance(facing, dict):
            _merge_relation(
                relation_index,
                _relation(
                    object_id,
                    "faces_accessible_space",
                    "room",
                    provenance="facing_constraint",
                    parameters=facing,
                ),
            )

    for edge in _legacy_relations(brief.get("relations", [])):
        if edge["source"] not in known_node_ids or edge["target"] not in known_node_ids:
            continue
        _merge_relation(relation_index, edge)

    hierarchy = _hierarchy_metadata(nodes, "room")
    node_kind_counts = Counter(str(node["node_kind"]) for node in nodes)
    relation_class_counts = Counter(
        str(edge["constraint_class"]) for edge in relation_index.values()
    )
    graph = {
        "schema": SCENE_GRAPH_SCHEMA,
        "root_id": "room",
        "nodes": nodes,
        "hierarchy": hierarchy,
        "relations": list(relation_index.values()),
        "constraint_scopes": deepcopy(brief.get("constraint_scopes", [])),
        "instance_groups": deepcopy(brief.get("instance_groups", [])),
        "relation_vocabulary": deepcopy(RELATION_VOCABULARY),
        "optimization_contract": {
            "primary_order": "hierarchy.breadth_first_order",
            "broad_phase": "semantic_dimensions_aabb",
            "narrow_phase": "optional_capability_bound_relation_aware_sdf",
            "scale_policy": "respect_each_object_dimension_policy",
            "reference_image_required": False,
        },
        "stats": {
            "node_count": len(nodes),
            "object_node_count": int(node_kind_counts.get("object", 0)),
            "structure_node_count": int(node_kind_counts.get("structure", 0)),
            "opening_node_count": int(node_kind_counts.get("architectural_opening", 0)),
            "relation_count": len(relation_index),
            "constraint_scope_count": len(brief.get("constraint_scopes", [])),
            "instance_group_count": len(brief.get("instance_groups", [])),
            "relation_class_counts": dict(sorted(relation_class_counts.items())),
            "max_depth": hierarchy["max_depth"],
        },
    }
    graph["validation"] = validate_typed_scene_graph(graph)
    return graph


def _normalize_yaw(value: float) -> float:
    result = value % 360.0
    return 0.0 if abs(result - 360.0) < 1e-8 else result


def _relative_pose(child: dict[str, float], parent: dict[str, float]) -> dict[str, float]:
    parent_yaw = math.radians(float(parent["yaw"]))
    dx = float(child["x"]) - float(parent["x"])
    dy = float(child["y"]) - float(parent["y"])
    return {
        "x": round(math.cos(parent_yaw) * dx + math.sin(parent_yaw) * dy, 6),
        "y": round(-math.sin(parent_yaw) * dx + math.cos(parent_yaw) * dy, 6),
        "z": round(float(child["z"]) - float(parent["z"]), 6),
        "yaw": round(_normalize_yaw(float(child["yaw"]) - float(parent["yaw"])), 6),
    }


def materialize_scene_graph(
    graph: dict[str, Any], objects: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Attach layout poses while preserving the semantic hierarchy and relations."""

    materialized = deepcopy(graph)
    object_by_id = {
        str(obj["id"]): obj for obj in objects if isinstance(obj, dict) and obj.get("id")
    }
    world_pose_by_id: dict[str, dict[str, float]] = {}
    for object_id, obj in object_by_id.items():
        world_pose_by_id[object_id] = {
            "x": float(obj.get("x", 0.0)),
            "y": float(obj.get("y", 0.0)),
            "z": float(obj.get("z", 0.0)),
            "yaw": _normalize_yaw(float(obj.get("yaw", 0.0))),
        }

    for node in materialized.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        obj = object_by_id.get(node_id)
        if obj is not None:
            node["source"] = _object_source(obj)
        world_pose = world_pose_by_id.get(node_id)
        if world_pose is None:
            continue
        parent_id = str(node.get("parent_id") or "")
        parent_pose = world_pose_by_id.get(parent_id)
        if parent_pose is not None:
            local_pose = _relative_pose(world_pose, parent_pose)
            local_reference = parent_id
            local_resolved = True
        elif parent_id in {"", "room", "floor"}:
            local_pose = deepcopy(world_pose)
            local_reference = parent_id or "room"
            local_resolved = True
        else:
            local_pose = None
            local_reference = parent_id
            local_resolved = False
        node["pose"] = {
            "world": deepcopy(world_pose),
            "local": local_pose,
            "local_reference": local_reference,
            "local_resolved": local_resolved,
        }
        if obj is not None and obj.get("rigid_body_pose_matrix_z_up") is not None:
            node["pose"]["world_rigid_body_matrix_z_up"] = deepcopy(obj["rigid_body_pose_matrix_z_up"])
            node["pose"]["rigid_body_origin"] = "metric_visual_bounds_center"

    materialized["layout_materialized"] = True
    materialized["materialized_object_count"] = len(world_pose_by_id)
    materialized["validation"] = validate_typed_scene_graph(materialized)
    return materialized
