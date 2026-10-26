"""Compile selected asset use restrictions into executable scene constraints."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .orientation import AXIS_VECTORS, WALL_INWARD_NORMALS, evaluate_facing


def requires_wall_front(obj: dict[str, Any]) -> bool:
    usage = set(obj.get("usage_constraints") or [])
    return "back_against_wall" in usage or (
        "front_only" in usage and ("wall_mounted" in usage or obj.get("placement_type") == "wall")
    )


def bind_asset_usage(scene: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    entries = {str(a["asset_id"]): a for a in manifest.get("assets", [])}
    rows = []
    for obj in scene.get("objects", []):
        entry = entries.get(str(obj.get("asset_id")), {})
        usage = sorted(set(obj.get("usage_constraints") or []) | set(entry.get("usage_constraints") or []))
        if not usage:
            continue
        obj["usage_constraints"] = usage
        if entry.get("asset_canonical_front"):
            obj["asset_canonical_front"] = {
                k: deepcopy(v) for k, v in entry["asset_canonical_front"].items()
                if k in {"axis", "source", "confidence"}
            }
        if requires_wall_front(obj):
            wall = str(obj.get("preferred_wall") or "")
            previous = obj.get("facing_constraint")
            if previous and (previous.get("mode") != "into_room" or (previous.get("wall") and previous["wall"] != wall)):
                raise ValueError(f"Asset use conflicts with requested facing for {obj['id']}")
            obj["facing_constraint"] = {
                **(previous or {}), "mode": "into_room", "wall": wall,
                "contact_face": "back", "strength": "hard",
                "provenance": "selected_asset_usage_constraints",
            }
        rows.append({"object_id": obj["id"], "asset_id": obj.get("asset_id"),
                     "canonical_front_evidence": deepcopy(entry.get("asset_canonical_front")),
                     "usage_constraints": usage, "facing_constraint": deepcopy(obj.get("facing_constraint"))})
    return {"schema": "asset_usage_resolution_v1", "results": rows}


def asset_usage_violations(obj: dict[str, Any], room: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not requires_wall_front(obj):
        return []
    failures = []
    constraint = obj.get("facing_constraint") or {}
    if constraint.get("mode") != "into_room" or str(constraint.get("wall") or obj.get("preferred_wall")) not in WALL_INWARD_NORMALS:
        failures.append("required wall-facing constraint is missing")
    front = obj.get("asset_canonical_front") or {}
    orientation = obj.get("asset_orientation") or {}
    if str(front.get("axis") or orientation.get("canonical_front_axis") or "").lower() not in AXIS_VECTORS:
        failures.append("required canonical front is unknown")
    status = evaluate_facing(obj, room)
    if status and not status["ok"]:
        failures.append("required front points away from the room")
    return [{"type": "asset_usage_constraint", "severity": "hard", "object_id": obj.get("id"), "reason": reason} for reason in failures]
