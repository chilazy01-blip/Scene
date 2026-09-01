from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .io_utils import run_codex_json, slugify
from .orientation import apply_facing_constraints, apply_relation_facing_constraints
from .scene_graph import materialize_scene_graph


def _rule_pose(room_type: str, object_id: str, room: dict[str, float]) -> tuple[float, float, float]:
    width = float(room["width"])
    length = float(room["length"])
    anchors: dict[str, dict[str, tuple[float, float, float]]] = {
        "bedroom": {
            "bed": (0.50, 0.74, 0),
            "nightstand_left": (0.25, 0.90, 0),
            "nightstand_right": (0.75, 0.90, 0),
            "wardrobe": (0.93, 0.53, 90),
            "dresser": (0.22, 0.10, 180),
        },
        "living_room": {
            "sofa": (0.50, 0.12, 0),
            "coffee_table": (0.50, 0.45, 0),
            "tv_stand": (0.50, 0.94, 0),
            "accent_chair": (0.12, 0.55, 90),
            "side_table_left": (0.25, 0.15, 0),
            "side_table_right": (0.75, 0.15, 0),
            "floor_lamp": (0.91, 0.67, 0),
        },
        "kitchen": {
            "refrigerator": (0.09, 0.34, 90),
            "sink_cabinet": (0.19, 0.91, 0),
            "stove": (0.42, 0.91, 0),
            "counter": (0.72, 0.91, 0),
            "dining_table": (0.55, 0.35, 0),
            "dining_chair_left": (0.38, 0.35, 90),
            "dining_chair_right": (0.72, 0.35, 270),
        },
        "study": {
            "desk": (0.50, 0.89, 0),
            "office_chair": (0.50, 0.62, 0),
            "bookcase": (0.91, 0.60, 90),
            "cabinet": (0.07, 0.55, 90),
            "floor_lamp": (0.15, 0.12, 0),
        },
        "restroom": {
            "toilet": (0.53, 0.87, 0),
            "vanity_sink": (0.86, 0.68, 90),
            "shower": (0.15, 0.78, 0),
            "vanity_mirror": (0.99, 0.68, 90),
            "laundry_basket": (0.22, 0.10, 0),
        },
    }
    anchor = anchors.get(room_type, {}).get(object_id)
    if anchor:
        return width * anchor[0], length * anchor[1], anchor[2]
    index = sum(ord(ch) for ch in object_id)
    return width * (0.25 + (index % 3) * 0.25), length * (0.25 + ((index // 3) % 3) * 0.25), 0.0


def rules_layout(brief: dict[str, Any]) -> dict[str, Any]:
    room = deepcopy(brief["room"])
    objects: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for spec in brief["objects"]:
        if spec.get("placement_type") == "support":
            continue
        x, y, yaw = _rule_pose(str(brief["room_type"]), str(spec["id"]), room)
        obj = deepcopy(spec)
        placement_type = str(obj.get("placement_type", "floor"))
        z = float(obj.get("mount_height") or 0.0) if placement_type == "wall" else 0.0
        if placement_type == "floor_covering":
            z = 0.01
        obj.update({"x": x, "y": y, "z": z, "yaw": yaw})
        objects.append(obj)
        by_id[str(obj["id"])] = obj
    orientation_changes = apply_facing_constraints(objects, room)
    for spec in brief["objects"]:
        if spec.get("placement_type") != "support":
            continue
        support = by_id.get(str(spec.get("support_id")))
        if not support:
            raise ValueError(f"Missing support object for {spec['id']}: {spec.get('support_id')}")
        obj = deepcopy(spec)
        offset = obj.get("support_offset") or [0.0, 0.0]
        dx, dy = float(offset[0]), float(offset[1])
        quarter_turns = int(round(float(support.get("yaw", 0.0)) / 90.0)) % 4
        if quarter_turns == 1:
            dx, dy = -dy, dx
        elif quarter_turns == 2:
            dx, dy = -dx, -dy
        elif quarter_turns == 3:
            dx, dy = dy, -dx
        obj.update(
            {
                "x": float(support["x"]) + dx,
                "y": float(support["y"]) + dy,
                "z": float(support["dimensions"]["height"]),
                "yaw": float(support.get("yaw", 0.0)),
            }
        )
        objects.append(obj)
    orientation_changes.extend(
        apply_relation_facing_constraints(objects, brief.get("relations", []))
    )
    plan = {
        "schema": "codex_trellis_layout_plan_v2",
        "scene_id": f"v2_{slugify(str(brief['room_type']))}",
        "room_type": brief["room_type"],
        "description": brief["expanded_description"],
        "styles": brief["styles"],
        "room": room,
        "architecture": deepcopy(brief["architecture"]),
        "objects": objects,
        "relations": deepcopy(brief["relations"]),
        "instance_groups": deepcopy(brief.get("instance_groups", [])),
        "object_budget": deepcopy(brief["object_budget"]),
        "camera_requirements": deepcopy(brief.get("camera_requirements", {})),
        "render_requirements": deepcopy(brief.get("render_requirements", {})),
        "planner": "deterministic_rules",
        "orientation_resolution": orientation_changes,
    }
    if isinstance(brief.get("scene_graph"), dict):
        plan["scene_graph"] = materialize_scene_graph(
            brief["scene_graph"], plan["objects"]
        )
    return plan


def _planner_brief(brief: dict[str, Any]) -> dict[str, Any]:
    """Keep the graph contract in the prompt without duplicating asset metadata."""

    result = deepcopy(brief)
    graph = result.get("scene_graph")
    if not isinstance(graph, dict):
        return result
    result["scene_graph"] = {
        "schema": graph.get("schema"),
        "root_id": graph.get("root_id"),
        "nodes": [
            {
                key: node.get(key)
                for key in (
                    "id",
                    "node_kind",
                    "semantic_type",
                    "parent_id",
                    "parent_relation",
                    "transform_space",
                )
            }
            for node in graph.get("nodes", [])
            if isinstance(node, dict)
        ],
        "hierarchy": {
            "breadth_first_order": graph.get("hierarchy", {}).get(
                "breadth_first_order", []
            ),
        },
        "relations": [
            {
                key: edge.get(key)
                for key in (
                    "source",
                    "type",
                    "target",
                    "constraint_class",
                    "strength",
                    "parameters",
                )
            }
            for edge in graph.get("relations", [])
            if isinstance(edge, dict)
        ],
    }
    return result


def _layout_prompt(brief: dict[str, Any]) -> str:
    planner_brief = _planner_brief(brief)
    object_catalog = [
        {
            key: obj.get(key)
            for key in (
                "id",
                "category",
                "dimensions",
                "placement_type",
                "support_id",
                "support_offset",
                "preferred_wall",
                "wall_constraint_strength",
                "mount_height",
                "asset_id",
                "asset_canonical_front",
                "asset_orientation",
                "asset_affordance",
                "facing_constraint",
                "instance_group_id",
                "instance_group_role",
                "instance_group_asset_family",
                "instance_group_asset_strategy",
            )
        }
        for obj in brief["objects"]
    ]
    return f"""
You are the spatial planner in a constrained text-to-3D room pipeline.
Choose coordinates for the exact object instances below. Do not add, remove, rename, or resize objects.

Scene brief:
{json.dumps(planner_brief, indent=2, ensure_ascii=False)}

Resolved object instances:
{json.dumps(object_catalog, indent=2, ensure_ascii=False)}

Return only JSON:
{{
  "scene_id": "short id",
  "room": {{"width": number, "length": number, "height": 2.7}},
  "objects": [
    {{
      "id": "exact provided id",
      "x": number,
      "y": number,
      "z": number,
      "yaw": 0|90|180|270,
      "facing_mode": "into_room|free",
      "contact_face": "back|none"
    }}
  ]
}}

Hard rules:
- Coordinates use a southwest-corner origin; x grows east and y grows north.
- Treat scene_graph as an immutable semantic contract: preserve its primary parents and satisfy
  hard typed relations. Return poses only; the SDK materializes world and parent-local transforms.
- Treat instance_groups as execution contracts. Preserve each member as an independent object,
  keep matched members visually coherent, and propose a compact ordered arrangement; the SDK may
  apply bounded member spacing and one shared translation after layout.
- Preserve the supplied architecture layer exactly; doors, windows, and floor are not furniture objects.
- Keep complete rotated footprints inside the room.
- Never overlap floor furniture.
- Keep the east-wall entry zone clear: the lower 1.2m of that wall and 1.1m inward.
- Objects with preferred_wall should stay close to that wall; this is mandatory only when
  wall_constraint_strength is hard. A hard aligned_with relation may instead define the relevant
  face/edge alignment.
- For objects with facing_constraint, use asset canonical-front metadata to put the declared
  contact_face toward the wall and the primary interaction face toward accessible room space.
  Return the semantic facing_mode and contact_face; the deterministic SDK will normalize yaw.
- Support objects must remain within their support_id footprint, apply the supplied support_offset, and have z equal to support height.
- Wall objects must remain flush with preferred_wall and preserve their supplied mount_height.
- Meet the hard minimum. target_max only controls automatic expansion and never permits dropping
  or merging explicit instances; hard_runtime_limit is the only absolute count guard.
- Treat camera_requirements as an executable composition contract. For a centered composition,
  keep the room's primary furniture group on the camera centerline. Preserve complete required
  object silhouettes and reduce front-view occlusion when those flags are enabled.
- Preserve a walkable path from the east-wall entry to the room interior.
- Use only the exact object ids listed above.
- Do not include markdown or text outside JSON.
""".strip()


def _normalize_codex_layout(raw: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
    raw_room = raw.get("room") if isinstance(raw.get("room"), dict) else {}
    baseline_room = brief["room"]
    room = {
        "width": min(8.0, max(4.0, float(raw_room.get("width", baseline_room["width"])))),
        "length": min(6.5, max(3.2, float(raw_room.get("length", baseline_room["length"])))),
        "height": min(3.5, max(2.4, float(raw_room.get("height", baseline_room["height"])))),
    }
    raw_objects = {
        str(item.get("id")): item
        for item in raw.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    }
    expected = {str(item["id"]): item for item in brief["objects"]}
    missing = sorted(set(expected) - set(raw_objects))
    if missing:
        raise ValueError("Codex layout omitted required object ids: " + ", ".join(missing))
    objects = []
    for object_id, spec in expected.items():
        pose = raw_objects[object_id]
        obj = deepcopy(spec)
        obj.update(
            {
                "x": float(pose.get("x", 0.0)),
                "y": float(pose.get("y", 0.0)),
                "z": float(pose.get("z", 0.0)),
                "yaw": float(pose.get("yaw", 0.0)),
            }
        )
        constraint = obj.get("facing_constraint")
        if isinstance(constraint, dict):
            expected_mode = str(constraint.get("mode") or "into_room")
            expected_contact = str(constraint.get("contact_face") or "back")
            obj["facing_decision"] = {
                "mode": expected_mode,
                "contact_face": expected_contact,
                "planner_response_mode": str(pose.get("facing_mode") or expected_mode),
                "planner_response_contact_face": str(
                    pose.get("contact_face") or expected_contact
                ),
                "source": "codex_semantics_with_sdk_normalization",
            }
        objects.append(obj)
    plan = {
        "schema": "codex_trellis_layout_plan_v2",
        "scene_id": slugify(str(raw.get("scene_id") or f"v2_{brief['room_type']}")),
        "room_type": brief["room_type"],
        "description": brief["expanded_description"],
        "styles": brief["styles"],
        "room": room,
        "architecture": deepcopy(brief.get("architecture", {})),
        "objects": objects,
        "relations": deepcopy(brief["relations"]),
        "instance_groups": deepcopy(brief.get("instance_groups", [])),
        "object_budget": deepcopy(brief.get("object_budget", {})),
        "camera_requirements": deepcopy(brief.get("camera_requirements", {})),
        "render_requirements": deepcopy(brief.get("render_requirements", {})),
        "planner": "codex_exec",
    }
    plan["orientation_resolution"] = apply_facing_constraints(
        plan["objects"], plan["room"]
    )
    plan["orientation_resolution"].extend(
        apply_relation_facing_constraints(
            plan["objects"], plan.get("relations", [])
        )
    )
    if isinstance(brief.get("scene_graph"), dict):
        plan["scene_graph"] = materialize_scene_graph(
            brief["scene_graph"], plan["objects"]
        )
    return plan


def codex_layout(brief: dict[str, Any], output_dir: Path, model: str) -> dict[str, Any]:
    raw = run_codex_json(
        _layout_prompt(brief), output_dir, stage="layout_plan", model=model
    )
    return _normalize_codex_layout(raw, brief)


def codex_repair_layout(
    plan: dict[str, Any],
    validation: dict[str, Any],
    output_dir: Path,
    *,
    model: str,
    iteration: int,
) -> dict[str, Any]:
    repair_prompt_plan = deepcopy(plan)
    if isinstance(plan.get("scene_graph"), dict):
        repair_prompt_plan["scene_graph"] = _planner_brief(
            {"scene_graph": plan["scene_graph"]}
        )["scene_graph"]
    prompt = f"""
Repair only the coordinates and yaw of this room layout.
Preserve room type, room dimensions, exact object ids, categories, assets, and dimensions.
Preserve the typed scene_graph primary hierarchy and hard relation edges.
Preserve facing_constraint. For wall-backed functional furniture, keep the back toward its wall
and the primary interaction face toward accessible room space.
Treat camera_requirements and composition violations as executable constraints. Do not fix a
walkway by moving the primary group off the requested camera centerline; rearrange secondary
objects first and preserve complete, minimally occluded required silhouettes.

Current plan:
{json.dumps(repair_prompt_plan, indent=2, ensure_ascii=False)}

Hard validation report:
{json.dumps(validation, indent=2, ensure_ascii=False)}

Return only JSON with this shape:
{{
  "scene_id": "same or short repaired id",
  "room": {{"width": number, "length": number, "height": number}},
  "objects": [{{"id": "exact id", "x": number, "y": number, "z": number, "yaw": 0|90|180|270}}]
}}
Do not include markdown or explanations.
""".strip()
    raw = run_codex_json(
        prompt,
        output_dir,
        stage=f"layout_repair_{iteration}",
        model=model,
    )
    brief_like = {
        "room": plan["room"],
        "architecture": plan.get("architecture", {}),
        "room_type": plan["room_type"],
        "expanded_description": plan["description"],
        "styles": plan.get("styles", []),
        "objects": plan["objects"],
        "relations": plan.get("relations", []),
        "scene_graph": plan.get("scene_graph", {}),
        "object_budget": plan.get("object_budget", {}),
        "camera_requirements": plan.get("camera_requirements", {}),
        "render_requirements": plan.get("render_requirements", {}),
    }
    repaired = _normalize_codex_layout(raw, brief_like)
    repaired["planner"] = "codex_repair"
    return repaired
