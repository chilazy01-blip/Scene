from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Iterable

from .spatial_constraints import compile_spatial_relations


SCOPE_DOMAINS = {
    "floor",
    "support_surface",
    "container_volume",
    "wall_surface",
    "functional_clearance",
}

SCOPE_KINDS = {
    "layout_group",
    "support_group",
    "containment_group",
    "functional_group",
}

RELATION_ALIASES = {
    "on": "supported_by",
    "against": "against_wall",
    "facing": "faces",
    "inside": "contained_in",
}


def _relation_parts(item: Any) -> tuple[str, str, str] | None:
    if isinstance(item, (list, tuple)) and len(item) == 3:
        source, relation_type, target = (str(value) for value in item)
    elif isinstance(item, dict):
        source = str(item.get("source") or item.get("subject") or "")
        relation_type = str(item.get("type") or item.get("predicate") or "")
        target = str(item.get("target") or item.get("object") or "")
    else:
        return None
    relation_type = RELATION_ALIASES.get(relation_type, relation_type)
    return source, relation_type, target


def relation_id(source: str, relation_type: str, target: str) -> str:
    return f"relation:{source}:{relation_type}:{target}"


def _available_relations(brief: dict[str, Any]) -> set[tuple[str, str, str]]:
    result = {
        parts
        for item in brief.get("relations", [])
        if (parts := _relation_parts(item)) is not None
    }
    for obj in brief.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        source = str(obj["id"])
        support_id = str(obj.get("support_id") or "")
        if support_id:
            result.add((source, "supported_by", support_id))
        container_id = str(obj.get("container_id") or "")
        if container_id:
            result.add((source, "contained_in", container_id))
        preferred_wall = str(obj.get("preferred_wall") or "")
        if preferred_wall:
            result.add((source, "against_wall", f"{preferred_wall}_wall"))
    return result


def _verified_evidence(evidence: str, prompt: str) -> bool:
    evidence = " ".join(evidence.lower().split())
    prompt = " ".join(prompt.lower().split())
    return bool(evidence and evidence in prompt)


def ground_constraint_scopes(
    brief: dict[str, Any], raw_scopes: Any
) -> dict[str, Any]:
    """Ground Codex grouping proposals without changing hierarchy or coordinates."""

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    scopes: list[dict[str, Any]] = []
    if raw_scopes is None:
        raw_scopes = []
    if not isinstance(raw_scopes, list):
        raw_scopes = []
        rejected.append({"reason": "constraint_scopes must be a list"})

    object_ids = {
        str(obj["id"])
        for obj in brief.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    known_nodes = object_ids | {
        "room",
        "floor",
        "north_wall",
        "south_wall",
        "east_wall",
        "west_wall",
    }
    available_relations = _available_relations(brief)
    prompt = str(brief.get("original_prompt") or "")
    seen_scope_ids: set[str] = set()

    for raw in raw_scopes[:24]:
        if not isinstance(raw, dict):
            rejected.append({"raw": deepcopy(raw), "reason": "scope must be an object"})
            continue
        scope_id = str(raw.get("scope_id") or "")
        domain = str(raw.get("domain") or "")
        scope_kind = str(raw.get("scope_kind") or "layout_group")
        root_id = str(raw.get("root_id") or "")
        evidence = str(raw.get("source_evidence") or "")[:500]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", scope_id):
            rejected.append({"raw": deepcopy(raw), "reason": "invalid scope_id"})
            continue
        if scope_id in seen_scope_ids:
            rejected.append({"raw": deepcopy(raw), "reason": "duplicate scope_id"})
            continue
        if domain not in SCOPE_DOMAINS:
            rejected.append({"raw": deepcopy(raw), "reason": "unsupported scope domain"})
            continue
        if scope_kind not in SCOPE_KINDS:
            rejected.append({"raw": deepcopy(raw), "reason": "unsupported scope_kind"})
            continue
        if not _verified_evidence(evidence, prompt):
            rejected.append(
                {"raw": deepcopy(raw), "reason": "source_evidence is not an exact prompt fragment"}
            )
            continue

        raw_members = raw.get("members")
        if not isinstance(raw_members, list):
            rejected.append({"raw": deepcopy(raw), "reason": "members must be a list"})
            continue
        members: list[dict[str, str]] = []
        member_ids: set[str] = set()
        member_error = ""
        for member in raw_members[:24]:
            if isinstance(member, str):
                object_id, role = member, "member"
            elif isinstance(member, dict):
                object_id = str(member.get("object_id") or "")
                role = str(member.get("role") or "member")
            else:
                member_error = "member must be an object or object id"
                break
            if object_id not in object_ids:
                member_error = f"unknown member object id: {object_id}"
                break
            if object_id in member_ids:
                member_error = f"duplicate member object id: {object_id}"
                break
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", role):
                member_error = f"invalid member role: {role}"
                break
            member_ids.add(object_id)
            members.append({"object_id": object_id, "role": role})
        if member_error or len(members) < 2:
            rejected.append(
                {
                    "raw": deepcopy(raw),
                    "reason": member_error or "scope requires at least two unique members",
                }
            )
            continue
        if root_id not in member_ids:
            rejected.append({"raw": deepcopy(raw), "reason": "root_id must be a scope member"})
            continue

        raw_refs = raw.get("relation_refs")
        if not isinstance(raw_refs, list) or not raw_refs:
            rejected.append(
                {"raw": deepcopy(raw), "reason": "relation_refs must be a non-empty list"}
            )
            continue
        refs: list[dict[str, str]] = []
        ref_error = ""
        seen_refs: set[tuple[str, str, str]] = set()
        for ref in raw_refs[:32]:
            parts = _relation_parts(ref)
            if parts is None:
                ref_error = "invalid relation reference"
                break
            source, relation_type, target = parts
            if source not in known_nodes or target not in known_nodes:
                ref_error = "relation reference contains an unknown node"
                break
            if source in object_ids and source not in member_ids:
                ref_error = f"relation source is not a scope member: {source}"
                break
            if target in object_ids and target not in member_ids:
                ref_error = f"relation target is not a scope member: {target}"
                break
            if parts not in available_relations:
                ref_error = f"relation reference is not grounded: {relation_id(*parts)}"
                break
            if parts in seen_refs:
                continue
            seen_refs.add(parts)
            refs.append(
                {
                    "id": relation_id(*parts),
                    "source": source,
                    "type": relation_type,
                    "target": target,
                }
            )
        if ref_error or not refs:
            rejected.append(
                {"raw": deepcopy(raw), "reason": ref_error or "no valid relation references"}
            )
            continue

        canonical = {
            "schema": "codex_trellis_constraint_scope_v1",
            "scope_id": scope_id,
            "domain": domain,
            "scope_kind": scope_kind,
            "root_id": root_id,
            "members": members,
            "relation_refs": refs,
            "source_evidence": evidence,
            "evidence_verified": True,
            "provenance": "codex_semantic_proposal",
            "semantic_effect": "advisory_constraint_scope",
        }
        scopes.append(canonical)
        accepted.append(deepcopy(canonical))
        seen_scope_ids.add(scope_id)

    memberships: dict[str, list[str]] = {}
    for scope in scopes:
        for member in scope["members"]:
            memberships.setdefault(member["object_id"], []).append(scope["scope_id"])
    overlapping = {
        object_id: sorted(scope_ids)
        for object_id, scope_ids in memberships.items()
        if len(scope_ids) > 1
    }
    brief["constraint_scopes"] = scopes
    report = {
        "schema": "codex_trellis_constraint_scope_grounding_v1",
        "mode": "codex_proposal_local_contract_validation",
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "overlapping_memberships": overlapping,
        "auto_merge_performed": False,
        "hierarchy_mutated": False,
        "coordinates_mutated": False,
    }
    brief["constraint_scope_grounding"] = report
    return report


def _minimum_dimensions(obj: dict[str, Any]) -> tuple[float, float]:
    dimensions = obj.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    width = float(dimensions.get("width", 0.0) or 0.0)
    length = float(dimensions.get("length", 0.0) or 0.0)
    policy = obj.get("dimension_policy")
    policy = policy if isinstance(policy, dict) else {}
    mode = str(policy.get("mode") or "fixed_physical")
    if mode == "uniform_scalable":
        scale_range = policy.get("uniform_scale_range")
        if isinstance(scale_range, list) and len(scale_range) == 2:
            scale = max(0.0, float(scale_range[0]))
            width *= scale
            length *= scale
    elif mode in {"axis_scalable", "opening_fit"}:
        ranges = policy.get("axis_scale_ranges")
        ranges = ranges if isinstance(ranges, dict) else {}
        for axis in ("width", "length"):
            scale_range = ranges.get(axis)
            if isinstance(scale_range, list) and len(scale_range) == 2:
                scale = max(0.0, float(scale_range[0]))
                if axis == "width":
                    width *= scale
                else:
                    length *= scale
    return width, length


def _axis_span_lower_bound(
    member_ids: list[str],
    extents: dict[str, float],
    edges: Iterable[tuple[str, str, float]],
) -> tuple[float, bool]:
    positions = {object_id: extents[object_id] for object_id in member_ids}
    edge_list = list(edges)
    changed = False
    for _ in range(len(member_ids)):
        changed = False
        for before, after, gap in edge_list:
            candidate = positions[before] + extents[before] + gap + extents[after]
            if candidate > positions[after] + 1e-9:
                positions[after] = candidate
                changed = True
        if not changed:
            break
    cycle = changed and bool(member_ids)
    span = max(
        (positions[object_id] + extents[object_id] for object_id in member_ids),
        default=0.0,
    )
    return span, cycle


def evaluate_constraint_scope_envelopes(brief: dict[str, Any]) -> dict[str, Any]:
    """Compute advisory necessary-condition bounds, never final layout coordinates."""

    objects_by_id = {
        str(obj["id"]): obj
        for obj in brief.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    relation_lookup = {
        relation["id"]: relation
        for relation in compile_spatial_relations(brief.get("relations", []))
    }
    room = brief.get("room") if isinstance(brief.get("room"), dict) else {}
    room_width = float(room.get("width", 0.0) or 0.0)
    room_length = float(room.get("length", 0.0) or 0.0)
    results: list[dict[str, Any]] = []

    for scope in brief.get("constraint_scopes", []):
        if not isinstance(scope, dict):
            continue
        member_ids = [
            str(member["object_id"])
            for member in scope.get("members", [])
            if isinstance(member, dict) and str(member.get("object_id") or "") in objects_by_id
        ]
        dimensions = {
            object_id: _minimum_dimensions(objects_by_id[object_id])
            for object_id in member_ids
        }
        width_extents = {key: value[0] / 2.0 for key, value in dimensions.items()}
        depth_extents = {key: value[1] / 2.0 for key, value in dimensions.items()}
        x_edges: list[tuple[str, str, float]] = []
        y_edges: list[tuple[str, str, float]] = []
        executable_count = 0
        unsupported_relation_ids: list[str] = []
        for ref in scope.get("relation_refs", []):
            relation = relation_lookup.get(str(ref.get("id") or ""))
            if relation is None:
                unsupported_relation_ids.append(str(ref.get("id") or ""))
                continue
            source = str(relation["source"])
            target = str(relation["target"])
            if source not in dimensions or target not in dimensions:
                unsupported_relation_ids.append(str(relation["id"]))
                continue
            relation_type = str(relation["type"])
            gap = float(relation["min_gap"])
            if relation_type == "left_of":
                x_edges.append((source, target, gap))
            elif relation_type == "right_of":
                x_edges.append((target, source, gap))
            elif relation_type == "in_front_of":
                y_edges.append((target, source, gap))
            else:
                unsupported_relation_ids.append(str(relation["id"]))
                continue
            executable_count += 1

        width, x_cycle = _axis_span_lower_bound(member_ids, width_extents, x_edges)
        depth, y_cycle = _axis_span_lower_bound(member_ids, depth_extents, y_edges)
        minimum_area = sum(width * length for width, length in dimensions.values())
        fits_direct = width <= room_width + 1e-9 and depth <= room_length + 1e-9
        fits_rotated = depth <= room_width + 1e-9 and width <= room_length + 1e-9
        area_fits = minimum_area <= room_width * room_length + 1e-9
        domain = str(scope.get("domain") or "")
        if x_cycle or y_cycle:
            status = "constraint_conflict"
        elif domain != "floor":
            status = "unsupported_domain"
        elif not area_fits or not (fits_direct or fits_rotated):
            status = "potentially_infeasible"
        elif executable_count == 0:
            status = "insufficient_relations"
        else:
            status = "not_ruled_out"
        results.append(
            {
                "scope_id": scope.get("scope_id"),
                "domain": domain,
                "status": status,
                "proof_level": "necessary_condition_only",
                "advisory_only": True,
                "minimum_envelope": {
                    "width": round(width, 6),
                    "depth": round(depth, 6),
                    "member_area": round(minimum_area, 6),
                },
                "room_capacity": {
                    "width": room_width,
                    "length": room_length,
                    "area": round(room_width * room_length, 6),
                },
                "executable_relation_count": executable_count,
                "unsupported_relation_ids": sorted(set(unsupported_relation_ids)),
                "ordering_cycle": x_cycle or y_cycle,
            }
        )

    status_counts = {
        status: sum(1 for result in results if result["status"] == status)
        for status in sorted({str(result["status"]) for result in results})
    }
    report = {
        "schema": "codex_trellis_constraint_scope_envelopes_v1",
        "evaluation_stage": "pre_asset_pre_layout",
        "scope_count": len(results),
        "status_counts": status_counts,
        "results": results,
        "blocks_pipeline": False,
    }
    brief["constraint_scope_envelopes"] = report
    return report
