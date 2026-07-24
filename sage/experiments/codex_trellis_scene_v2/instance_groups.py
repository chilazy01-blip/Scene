from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .orientation import CARDINAL_YAWS, world_front_vector


GROUP_KINDS = {"paired_instances", "matched_set"}
ARRANGEMENTS = {"side_by_side", "mirrored_pair", "row"}
REFERENCE_FRAMES = {"room", "anchor_local"}
ANCHOR_ZONES = {"front", "near", "free"}
ASSET_MATCH_MODES = {"same_family", "same_asset"}


def _verified_evidence(evidence: str, prompt: str) -> bool:
    evidence = " ".join(evidence.lower().split())
    prompt = " ".join(prompt.lower().split())
    return bool(evidence and evidence in prompt)


def _number(
    value: Any,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result):
        result = default
    return min(maximum, max(minimum, result))


def _canonical_group(
    raw: dict[str, Any],
    *,
    object_ids: set[str],
    prompt: str,
) -> tuple[dict[str, Any] | None, str]:
    group_id = str(raw.get("group_id") or "")
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", group_id):
        return None, "invalid group_id"
    group_kind = str(raw.get("group_kind") or "paired_instances")
    if group_kind not in GROUP_KINDS:
        return None, "unsupported group_kind"
    evidence = str(raw.get("source_evidence") or "")[:500]
    if not _verified_evidence(evidence, prompt):
        return None, "source_evidence is not an exact prompt fragment"

    raw_members = raw.get("members")
    if not isinstance(raw_members, list):
        return None, "members must be a list"
    members: list[dict[str, str]] = []
    member_ids: set[str] = set()
    for index, member in enumerate(raw_members[:12]):
        if isinstance(member, str):
            object_id = member
            role = f"member_{index + 1}"
        elif isinstance(member, dict):
            object_id = str(member.get("object_id") or "")
            role = str(member.get("role") or f"member_{index + 1}")
        else:
            return None, "member must be an object or object id"
        if object_id not in object_ids:
            return None, f"unknown member object id: {object_id}"
        if object_id in member_ids:
            return None, f"duplicate member object id: {object_id}"
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", role):
            return None, f"invalid member role: {role}"
        member_ids.add(object_id)
        members.append({"object_id": object_id, "role": role})

    cardinality = int(raw.get("cardinality") or len(members))
    if cardinality < 2 or cardinality != len(members):
        return None, "cardinality must equal the number of unique members"
    if group_kind == "paired_instances" and cardinality != 2:
        return None, "paired_instances requires exactly two members"

    raw_asset = raw.get("asset_contract")
    raw_asset = raw_asset if isinstance(raw_asset, dict) else {}
    match_mode = str(raw_asset.get("match_mode") or "same_family")
    if match_mode not in ASSET_MATCH_MODES:
        return None, "unsupported asset match_mode"
    fallback = str(raw_asset.get("fallback") or "same_asset_reuse")
    if fallback not in {"same_asset_reuse", "shared_generation_spec", "reject"}:
        return None, "unsupported asset fallback"

    raw_layout = raw.get("layout_contract")
    raw_layout = raw_layout if isinstance(raw_layout, dict) else {}
    arrangement = str(raw_layout.get("arrangement") or "side_by_side")
    if arrangement not in ARRANGEMENTS:
        return None, "unsupported layout arrangement"
    reference_frame = str(raw_layout.get("reference_frame") or "room")
    if reference_frame not in REFERENCE_FRAMES:
        return None, "unsupported layout reference_frame"
    anchor_id = str(raw_layout.get("anchor_id") or "")
    if anchor_id and anchor_id not in object_ids:
        return None, f"unknown layout anchor_id: {anchor_id}"
    anchor_zone = str(raw_layout.get("anchor_zone") or "free")
    if anchor_zone not in ANCHOR_ZONES:
        return None, "unsupported layout anchor_zone"
    min_gap = _number(raw_layout.get("min_gap"), 0.03, minimum=0.0, maximum=1.0)
    max_gap = _number(raw_layout.get("max_gap"), 0.20, minimum=min_gap, maximum=2.0)
    target_gap = _number(
        raw_layout.get("target_gap"),
        min(0.08, max_gap),
        minimum=min_gap,
        maximum=max_gap,
    )
    orientation_tolerance = _number(
        raw_layout.get("orientation_tolerance_degrees"),
        15.0,
        minimum=0.0,
        maximum=90.0,
    )
    anchor_min_gap = _number(
        raw_layout.get("anchor_min_gap"), 0.05, minimum=0.0, maximum=2.0
    )
    anchor_max_gap = _number(
        raw_layout.get("anchor_max_gap"),
        0.80,
        minimum=anchor_min_gap,
        maximum=3.0,
    )
    anchor_target_gap = _number(
        raw_layout.get("anchor_target_gap"),
        0.25,
        minimum=anchor_min_gap,
        maximum=anchor_max_gap,
    )
    return (
        {
            "schema": "codex_trellis_instance_group_v1",
            "group_id": group_id,
            "group_kind": group_kind,
            "cardinality": cardinality,
            "members": members,
            "asset_contract": {
                "match_mode": match_mode,
                "fallback": fallback,
                "require_distinct_roles": bool(
                    raw_asset.get("require_distinct_roles", group_kind == "paired_instances")
                ),
            },
            "layout_contract": {
                "arrangement": arrangement,
                "reference_frame": reference_frame,
                "anchor_id": anchor_id or None,
                "anchor_zone": anchor_zone,
                "anchor_min_gap": anchor_min_gap,
                "anchor_target_gap": anchor_target_gap,
                "anchor_max_gap": anchor_max_gap,
                "shared_orientation": bool(
                    raw_layout.get("shared_orientation", True)
                ),
                "orientation_tolerance_degrees": orientation_tolerance,
                "min_gap": min_gap,
                "target_gap": target_gap,
                "max_gap": max_gap,
                "allow_member_respacing": bool(
                    raw_layout.get("allow_member_respacing", True)
                ),
                "allow_rigid_translation": bool(
                    raw_layout.get("allow_rigid_translation", True)
                ),
            },
            "source_evidence": evidence,
            "evidence_verified": True,
            "provenance": str(raw.get("provenance") or "codex_semantic_proposal"),
            "semantic_effect": "asset_and_after_layout_execution_group",
            "members_remain_independent_instances": True,
        },
        "",
    )


def deterministic_pair_groups(
    prompt: str,
    objects: list[dict[str, Any]],
    pair_instance_counts: dict[str, int],
) -> list[dict[str, Any]]:
    """Create only unambiguous one-pair groups already proven by quantity parsing."""

    result: list[dict[str, Any]] = []
    lowered = prompt.lower()
    for category, pair_size in sorted(pair_instance_counts.items()):
        if int(pair_size) != 2:
            continue
        members = [
            obj
            for obj in objects
            if str(obj.get("category") or "") == category
            and str(obj.get("provenance") or "") == "user_explicit"
        ]
        if len(members) != 2:
            continue
        direct_pattern = re.compile(
            rf"(?:(?:exactly|at\s+least)\s+)?(?:1|one|a)\s+"
            rf"(?:[a-z-]+\s+){{0,2}}pair\s+of\s+{re.escape(category)}s?(?![a-z0-9])"
        )
        match = direct_pattern.search(lowered)
        evidence_span: tuple[int, int] | None = (
            (match.start(), match.end()) if match else None
        )
        if match:
            containing_segment = next(
                (
                    segment_match
                    for segment_match in re.finditer(r"[^.!?。！？;；]+", lowered)
                    if segment_match.start() <= match.start()
                    and segment_match.end() >= match.end()
                ),
                None,
            )
            if containing_segment is not None:
                evidence_span = (
                    containing_segment.start(),
                    containing_segment.end(),
                )
        if evidence_span is None:
            for segment_match in re.finditer(r"[^.!?。！？;；]+", lowered):
                segment = segment_match.group(0)
                if (
                    re.search(r"\bpair\b", segment)
                    and re.search(
                        rf"(?<![a-z]){re.escape(category)}s?(?![a-z0-9])",
                        segment,
                    )
                ):
                    evidence_span = (
                        segment_match.start(),
                        segment_match.end(),
                    )
                    break
        if evidence_span is None:
            continue
        raw = {
            "group_id": f"explicit_{category}_pair",
            "group_kind": "paired_instances",
            "cardinality": 2,
            "members": [
                {"object_id": str(members[0]["id"]), "role": "left_member"},
                {"object_id": str(members[1]["id"]), "role": "right_member"},
            ],
            "asset_contract": {
                "match_mode": "same_family",
                "fallback": "same_asset_reuse",
                "require_distinct_roles": True,
            },
            "layout_contract": {
                "arrangement": "side_by_side",
                "reference_frame": "room",
                "anchor_id": None,
                "anchor_zone": "free",
                "shared_orientation": True,
                "orientation_tolerance_degrees": 15.0,
                "min_gap": 0.03,
                "target_gap": 0.08,
                "max_gap": 0.20,
                "allow_member_respacing": True,
                "allow_rigid_translation": True,
            },
            "source_evidence": prompt[evidence_span[0] : evidence_span[1]].strip(),
            "provenance": "deterministic_explicit_pair",
        }
        evidence_lowered = str(raw["source_evidence"]).lower()
        beds = [
            obj for obj in objects if str(obj.get("category") or "") == "bed"
        ]
        if (
            len(beds) == 1
            and re.search(r"\bfoot\b", evidence_lowered)
            and re.search(r"\bbed\b", evidence_lowered)
        ):
            raw["layout_contract"].update(
                {
                    "anchor_id": str(beds[0]["id"]),
                    "anchor_zone": "front",
                    "anchor_min_gap": 0.05,
                    "anchor_target_gap": 0.25,
                    "anchor_max_gap": 0.80,
                }
            )
        canonical, reason = _canonical_group(
            raw,
            object_ids={str(obj["id"]) for obj in objects},
            prompt=prompt,
        )
        if canonical is not None and not reason:
            result.append(canonical)
    return result


def ground_instance_groups(
    brief: dict[str, Any], raw_groups: Any
) -> dict[str, Any]:
    """Validate Codex execution groups and forbid ambiguous rigid membership."""

    existing = [
        deepcopy(group)
        for group in brief.get("instance_groups", [])
        if isinstance(group, dict)
    ]
    groups = existing
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if raw_groups is None:
        raw_groups = []
    if not isinstance(raw_groups, list):
        raw_groups = []
        rejected.append({"reason": "instance_groups must be a list"})

    object_ids = {
        str(obj["id"])
        for obj in brief.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    prompt = str(brief.get("original_prompt") or "")
    for raw in raw_groups[:16]:
        if not isinstance(raw, dict):
            rejected.append({"raw": deepcopy(raw), "reason": "group must be an object"})
            continue
        canonical, reason = _canonical_group(
            raw,
            object_ids=object_ids,
            prompt=prompt,
        )
        if canonical is None:
            rejected.append({"raw": deepcopy(raw), "reason": reason})
            continue
        member_ids = {
            str(member["object_id"]) for member in canonical["members"]
        }
        exact_index = next(
            (
                index
                for index, group in enumerate(groups)
                if {
                    str(member.get("object_id") or "")
                    for member in group.get("members", [])
                    if isinstance(member, dict)
                }
                == member_ids
            ),
            None,
        )
        if exact_index is not None:
            baseline = groups[exact_index]
            canonical["group_id"] = str(baseline.get("group_id") or canonical["group_id"])
            canonical["provenance"] = "deterministic_pair_with_codex_refinement"
            groups[exact_index] = canonical
            accepted.append(deepcopy(canonical))
            continue
        occupied = {
            str(member.get("object_id") or "")
            for group in groups
            for member in group.get("members", [])
            if isinstance(group, dict) and isinstance(member, dict)
        }
        overlap = sorted(member_ids & occupied)
        if overlap:
            rejected.append(
                {
                    "raw": deepcopy(raw),
                    "reason": "object already belongs to another rigid instance group",
                    "overlapping_object_ids": overlap,
                }
            )
            continue
        if any(str(group.get("group_id") or "") == canonical["group_id"] for group in groups):
            rejected.append({"raw": deepcopy(raw), "reason": "duplicate group_id"})
            continue
        groups.append(canonical)
        accepted.append(deepcopy(canonical))

    memberships: dict[str, str] = {}
    conflicts: dict[str, list[str]] = {}
    for group in groups:
        group_id = str(group.get("group_id") or "")
        for member in group.get("members", []):
            if not isinstance(member, dict):
                continue
            object_id = str(member.get("object_id") or "")
            if object_id in memberships:
                conflicts.setdefault(object_id, [memberships[object_id]]).append(group_id)
            else:
                memberships[object_id] = group_id
    brief["instance_groups"] = groups
    report = {
        "schema": "codex_trellis_instance_group_grounding_v1",
        "mode": "deterministic_pair_plus_codex_contract_validation",
        "deterministic_group_count": sum(
            str(group.get("provenance") or "").startswith("deterministic")
            for group in groups
        ),
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "group_count": len(groups),
        "exclusive_membership_conflicts": conflicts,
        "hierarchy_mutated": False,
        "coordinates_mutated": False,
    }
    brief["instance_group_grounding"] = report
    return report


def member_group_index(groups: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(groups, list):
        return result
    for group in groups:
        if not isinstance(group, dict):
            continue
        for member in group.get("members", []):
            if not isinstance(member, dict):
                continue
            object_id = str(member.get("object_id") or "")
            if object_id:
                result[object_id] = {
                    "group": group,
                    "member": member,
                }
    return result


def _footprint(obj: dict[str, Any]) -> tuple[float, float]:
    dimensions = obj.get("dimensions")
    dimensions = dimensions if isinstance(dimensions, dict) else {}
    width = float(dimensions.get("width", 0.0) or 0.0)
    length = float(dimensions.get("length", 0.0) or 0.0)
    if int(round(float(obj.get("yaw", 0.0) or 0.0) / 90.0)) % 2:
        return length, width
    return width, length


def _aabb(obj: dict[str, Any]) -> tuple[float, float, float, float]:
    width, length = _footprint(obj)
    x = float(obj.get("x", 0.0) or 0.0)
    y = float(obj.get("y", 0.0) or 0.0)
    return x - width / 2.0, y - length / 2.0, x + width / 2.0, y + length / 2.0


def _rectangle_gap(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx0, ly0, lx1, ly1 = _aabb(left)
    rx0, ry0, rx1, ry1 = _aabb(right)
    dx = max(rx0 - lx1, lx0 - rx1, 0.0)
    dy = max(ry0 - ly1, ly0 - ry1, 0.0)
    return math.hypot(dx, dy)


def _angle_error(
    actual: tuple[float, float], expected: tuple[float, float]
) -> float:
    dot = max(-1.0, min(1.0, actual[0] * expected[0] + actual[1] * expected[1]))
    return math.degrees(math.acos(dot))


def _group_asset_key(obj: dict[str, Any]) -> str:
    return str(
        obj.get("instance_group_asset_family")
        or obj.get("asset_family_id")
        or obj.get("asset_generation_key")
        or ""
    )


def validate_instance_groups(
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = plan.get("instance_groups")
    groups = groups if isinstance(groups, list) else []
    objects = [
        obj for obj in plan.get("objects", []) if isinstance(obj, dict) and obj.get("id")
    ]
    by_id = {str(obj["id"]): obj for obj in objects}
    violations: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    seen_members: dict[str, str] = {}

    for group in groups:
        if not isinstance(group, dict):
            violations.append(
                {"type": "instance_group_contract", "severity": "hard", "reason": "group is not an object"}
            )
            continue
        group_id = str(group.get("group_id") or "")
        member_rows = [
            member for member in group.get("members", []) if isinstance(member, dict)
        ]
        member_ids = [str(member.get("object_id") or "") for member in member_rows]
        missing = sorted(object_id for object_id in member_ids if object_id not in by_id)
        duplicates = sorted(
            {object_id for object_id in member_ids if member_ids.count(object_id) > 1}
        )
        overlapping = []
        for object_id in member_ids:
            if object_id in seen_members:
                overlapping.append(object_id)
            else:
                seen_members[object_id] = group_id
        cardinality_ok = int(group.get("cardinality", 0) or 0) == len(member_ids)
        if missing or duplicates or overlapping or not cardinality_ok:
            violations.append(
                {
                    "type": "instance_group_contract",
                    "severity": "hard",
                    "group_id": group_id,
                    "missing_member_ids": missing,
                    "duplicate_member_ids": duplicates,
                    "overlapping_member_ids": sorted(set(overlapping)),
                    "cardinality_ok": cardinality_ok,
                }
            )
            results.append({"group_id": group_id, "ok": False, "contract_ok": False})
            continue

        members = [by_id[object_id] for object_id in member_ids]
        layout = group.get("layout_contract")
        layout = layout if isinstance(layout, dict) else {}
        min_gap = float(layout.get("min_gap", 0.03) or 0.03)
        max_gap = float(layout.get("max_gap", 0.20) or 0.20)
        gaps = [
            _rectangle_gap(members[index], members[index + 1])
            for index in range(len(members) - 1)
        ]
        spacing_ok = all(min_gap - 1e-6 <= gap <= max_gap + 1e-6 for gap in gaps)
        if not spacing_ok:
            violations.append(
                {
                    "type": "instance_group_spacing",
                    "severity": "hard",
                    "group_id": group_id,
                    "member_ids": member_ids,
                    "gaps": [round(gap, 6) for gap in gaps],
                    "min_gap": min_gap,
                    "max_gap": max_gap,
                }
            )

        roles = [str(member.get("role") or "") for member in member_rows]
        arrangement_ok = True
        if "left_member" in roles and "right_member" in roles:
            left = members[roles.index("left_member")]
            right = members[roles.index("right_member")]
            if str(layout.get("reference_frame") or "room") == "room":
                signed_order = float(right.get("x", 0.0)) - float(
                    left.get("x", 0.0)
                )
            else:
                front = world_front_vector(members[0])
                right_axis = (front[1], -front[0])
                signed_order = (
                    float(right.get("x", 0.0)) - float(left.get("x", 0.0))
                ) * right_axis[0] + (
                    float(right.get("y", 0.0)) - float(left.get("y", 0.0))
                ) * right_axis[1]
            arrangement_ok = signed_order > 1e-6
            if not arrangement_ok:
                violations.append(
                    {
                        "type": "instance_group_role_order",
                        "severity": "hard",
                        "group_id": group_id,
                        "left_member_id": str(left["id"]),
                        "right_member_id": str(right["id"]),
                        "reference_frame": str(
                            layout.get("reference_frame") or "room"
                        ),
                        "signed_order": round(signed_order, 6),
                    }
                )

        anchor_ok = True
        anchor_gap: float | None = None
        anchor_id = str(layout.get("anchor_id") or "")
        anchor_zone = str(layout.get("anchor_zone") or "free")
        anchor = by_id.get(anchor_id)
        if anchor_id and anchor is None:
            anchor_ok = False
            violations.append(
                {
                    "type": "instance_group_anchor_missing",
                    "severity": "hard",
                    "group_id": group_id,
                    "anchor_id": anchor_id,
                }
            )
        elif anchor is not None and anchor_zone != "free":
            min_x = min(_aabb(member)[0] for member in members)
            min_y = min(_aabb(member)[1] for member in members)
            max_x = max(_aabb(member)[2] for member in members)
            max_y = max(_aabb(member)[3] for member in members)
            proxy = {
                "x": (min_x + max_x) / 2.0,
                "y": (min_y + max_y) / 2.0,
                "yaw": 0.0,
                "dimensions": {
                    "width": max_x - min_x,
                    "length": max_y - min_y,
                },
            }
            anchor_gap = _rectangle_gap(proxy, anchor)
            min_anchor_gap = float(layout.get("anchor_min_gap", 0.05) or 0.05)
            max_anchor_gap = float(layout.get("anchor_max_gap", 0.80) or 0.80)
            direction_ok = True
            if anchor_zone == "front":
                front = world_front_vector(anchor)
                delta = (
                    float(proxy["x"]) - float(anchor.get("x", 0.0) or 0.0),
                    float(proxy["y"]) - float(anchor.get("y", 0.0) or 0.0),
                )
                direction_ok = delta[0] * front[0] + delta[1] * front[1] > 0.0
            anchor_ok = (
                min_anchor_gap - 1e-6
                <= anchor_gap
                <= max_anchor_gap + 1e-6
                and direction_ok
            )
            if not anchor_ok:
                violations.append(
                    {
                        "type": "instance_group_anchor_placement",
                        "severity": "hard",
                        "group_id": group_id,
                        "anchor_id": anchor_id,
                        "anchor_zone": anchor_zone,
                        "gap": round(anchor_gap, 6),
                        "min_gap": min_anchor_gap,
                        "max_gap": max_anchor_gap,
                        "direction_ok": direction_ok,
                    }
                )

        orientation_errors: list[float] = []
        orientation_ok = True
        if bool(layout.get("shared_orientation", True)) and len(members) > 1:
            expected = world_front_vector(members[0])
            orientation_errors = [
                _angle_error(world_front_vector(member), expected)
                for member in members[1:]
            ]
            tolerance = float(
                layout.get("orientation_tolerance_degrees", 15.0) or 15.0
            )
            orientation_ok = all(error <= tolerance + 1e-6 for error in orientation_errors)
            if not orientation_ok:
                violations.append(
                    {
                        "type": "instance_group_orientation",
                        "severity": "hard",
                        "group_id": group_id,
                        "member_ids": member_ids,
                        "angle_errors_degrees": [
                            round(error, 6) for error in orientation_errors
                        ],
                        "tolerance_degrees": tolerance,
                    }
                )

        asset_keys = [_group_asset_key(member) for member in members]
        resolved_assets = all(str(member.get("asset_source") or "") for member in members)
        asset_match_ok = not resolved_assets or (
            bool(asset_keys[0]) and len(set(asset_keys)) == 1
        )
        if not asset_match_ok:
            violations.append(
                {
                    "type": "instance_group_asset_match",
                    "severity": "hard",
                    "group_id": group_id,
                    "member_ids": member_ids,
                    "asset_family_keys": asset_keys,
                }
            )

        handedness = [
            str(member.get("asset_pair_role") or "") for member in members
        ]
        handedness_verified = len(set(handedness) - {""}) == len(members)
        asset_contract = group.get("asset_contract")
        asset_contract = asset_contract if isinstance(asset_contract, dict) else {}
        if (
            resolved_assets
            and bool(asset_contract.get("require_distinct_roles", False))
            and not handedness_verified
        ):
            violations.append(
                {
                    "type": "instance_group_handedness_unverified",
                    "severity": "soft",
                    "group_id": group_id,
                    "member_ids": member_ids,
                    "reason": "matching assets are usable, but distinct left/right geometry is not verified",
                }
            )
        results.append(
            {
                "group_id": group_id,
                "member_ids": member_ids,
                "contract_ok": True,
                "spacing_ok": spacing_ok,
                "arrangement_ok": arrangement_ok,
                "anchor_ok": anchor_ok,
                "anchor_gap": (
                    round(anchor_gap, 6) if anchor_gap is not None else None
                ),
                "orientation_ok": orientation_ok,
                "asset_match_ok": asset_match_ok,
                "handedness_verified": handedness_verified,
                "gaps": [round(gap, 6) for gap in gaps],
                "orientation_errors_degrees": [
                    round(error, 6) for error in orientation_errors
                ],
                "ok": (
                    spacing_ok
                    and arrangement_ok
                    and anchor_ok
                    and orientation_ok
                    and asset_match_ok
                ),
            }
        )

    return (
        violations,
        {
            "schema": "codex_trellis_instance_group_validation_v1",
            "group_count": len(groups),
            "valid_count": sum(bool(result.get("ok")) for result in results),
            "invalid_count": sum(not bool(result.get("ok")) for result in results),
            "hard_violation_count": sum(
                violation["severity"] == "hard" for violation in violations
            ),
            "soft_violation_count": sum(
                violation["severity"] == "soft" for violation in violations
            ),
            "exclusive_rigid_membership": True,
            "members_remain_independent_instances": True,
            "results": results,
        },
    )


def _solve_yaw_for_front(
    obj: dict[str, Any], expected: tuple[float, float]
) -> float:
    current = float(obj.get("yaw", 0.0) or 0.0) % 360.0
    return min(
        CARDINAL_YAWS,
        key=lambda yaw: (
            _angle_error(world_front_vector(obj, yaw=yaw), expected),
            abs((yaw - current + 180.0) % 360.0 - 180.0),
            yaw,
        ),
    )


def _overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    return not (
        left[2] + margin <= right[0]
        or right[2] + margin <= left[0]
        or left[3] + margin <= right[1]
        or right[3] + margin <= left[1]
    )


def apply_instance_group_postprocess(
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Compact matched sets, then move them only by a shared translation."""

    groups = plan.get("instance_groups")
    groups = groups if isinstance(groups, list) else []
    objects = [
        obj for obj in plan.get("objects", []) if isinstance(obj, dict) and obj.get("id")
    ]
    by_id = {str(obj["id"]): obj for obj in objects}
    room = plan.get("room") if isinstance(plan.get("room"), dict) else {}
    room_width = float(room.get("width", 0.0) or 0.0)
    room_length = float(room.get("length", 0.0) or 0.0)
    reports: list[dict[str, Any]] = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "")
        member_rows = [
            member for member in group.get("members", []) if isinstance(member, dict)
        ]
        members = [
            by_id[str(member.get("object_id") or "")]
            for member in member_rows
            if str(member.get("object_id") or "") in by_id
        ]
        if len(members) < 2 or len(members) != len(member_rows):
            reports.append(
                {"group_id": group_id, "status": "skipped_invalid_members"}
            )
            continue
        if any(str(member.get("placement_type") or "floor") != "floor" for member in members):
            reports.append(
                {"group_id": group_id, "status": "skipped_non_floor_group"}
            )
            continue
        layout = group.get("layout_contract")
        layout = layout if isinstance(layout, dict) else {}
        before = {
            str(member["id"]): {
                "x": float(member.get("x", 0.0) or 0.0),
                "y": float(member.get("y", 0.0) or 0.0),
                "yaw": float(member.get("yaw", 0.0) or 0.0),
            }
            for member in members
        }
        expected_front = world_front_vector(members[0])
        facing_sources = {
            str(relation.get("source") or "")
            for relation in plan.get("relations", [])
            if isinstance(relation, dict)
            and str(relation.get("type") or "") in {"faces", "facing"}
        }
        if bool(layout.get("shared_orientation", True)):
            for member in members[1:]:
                if member.get("facing_constraint") or str(member["id"]) in facing_sources:
                    continue
                member["yaw"] = _solve_yaw_for_front(member, expected_front)

        center_x = sum(float(member.get("x", 0.0) or 0.0) for member in members) / len(members)
        center_y = sum(float(member.get("y", 0.0) or 0.0) for member in members) / len(members)
        target_gap = float(layout.get("target_gap", 0.08) or 0.08)
        right_axis = (
            (1.0, 0.0)
            if str(layout.get("reference_frame") or "room") == "room"
            else (expected_front[1], -expected_front[0])
        )
        roles = [str(row.get("role") or "") for row in member_rows]
        order = list(range(len(members)))
        if "left_member" in roles and "right_member" in roles:
            order = [roles.index("left_member"), roles.index("right_member")]

        if bool(layout.get("allow_member_respacing", True)):
            extents = []
            for index in order:
                width, length = _footprint(members[index])
                extents.append(
                    abs(right_axis[0]) * width / 2.0
                    + abs(right_axis[1]) * length / 2.0
                )
            total_span = sum(extent * 2.0 for extent in extents) + target_gap * (
                len(extents) - 1
            )
            cursor = -total_span / 2.0
            for extent, member_index in zip(extents, order):
                offset = cursor + extent
                members[member_index]["x"] = center_x + right_axis[0] * offset
                members[member_index]["y"] = center_y + right_axis[1] * offset
                cursor += extent * 2.0 + target_gap

        nonmembers = [obj for obj in objects if obj not in members]
        candidate_translations: list[tuple[float, float]] = []
        anchor_id = str(layout.get("anchor_id") or "")
        anchor_zone = str(layout.get("anchor_zone") or "free")
        anchor = by_id.get(anchor_id)
        if anchor is not None and anchor_zone == "front":
            anchor_front = world_front_vector(anchor)
            anchor_width, anchor_length = _footprint(anchor)
            anchor_extent = (
                abs(anchor_front[0]) * anchor_width / 2.0
                + abs(anchor_front[1]) * anchor_length / 2.0
            )
            compact_center_x = sum(float(member["x"]) for member in members) / len(members)
            compact_center_y = sum(float(member["y"]) for member in members) / len(members)
            group_extent = max(
                abs(
                    (float(member["x"]) - compact_center_x) * anchor_front[0]
                    + (float(member["y"]) - compact_center_y) * anchor_front[1]
                )
                + (
                    abs(anchor_front[0]) * _footprint(member)[0] / 2.0
                    + abs(anchor_front[1]) * _footprint(member)[1] / 2.0
                )
                for member in members
            )
            target_distance = (
                anchor_extent
                + group_extent
                + float(layout.get("anchor_target_gap", 0.25) or 0.25)
            )
            target_center_x = float(anchor.get("x", 0.0) or 0.0) + anchor_front[0] * target_distance
            target_center_y = float(anchor.get("y", 0.0) or 0.0) + anchor_front[1] * target_distance
            anchor_translation = (
                target_center_x - compact_center_x,
                target_center_y - compact_center_y,
            )
            lateral_offsets = [0.0]
            for step in range(1, 16):
                lateral_offsets.extend([step * 0.1, -step * 0.1])
            forward_offsets = [0.0, 0.15, -0.15, 0.30, -0.20]
            for forward_offset in forward_offsets:
                for lateral_offset in lateral_offsets:
                    candidate_translations.append(
                        (
                            anchor_translation[0]
                            + right_axis[0] * lateral_offset
                            + anchor_front[0] * forward_offset,
                            anchor_translation[1]
                            + right_axis[1] * lateral_offset
                            + anchor_front[1] * forward_offset,
                        )
                    )
        candidate_translations.append((0.0, 0.0))
        if bool(layout.get("allow_rigid_translation", True)):
            for radius in (0.1, 0.2, 0.3, 0.4, 0.5):
                candidate_translations.extend(
                    [
                        (radius, 0.0),
                        (-radius, 0.0),
                        (0.0, radius),
                        (0.0, -radius),
                        (radius, radius),
                        (radius, -radius),
                        (-radius, radius),
                        (-radius, -radius),
                    ]
                )
        chosen: tuple[float, float] | None = None
        for dx, dy in candidate_translations:
            boxes = []
            valid = True
            for member in members:
                member["x"] = float(member["x"]) + dx
                member["y"] = float(member["y"]) + dy
                box = _aabb(member)
                member["x"] = float(member["x"]) - dx
                member["y"] = float(member["y"]) - dy
                if (
                    box[0] < 0.05
                    or box[1] < 0.05
                    or box[2] > room_width - 0.05
                    or box[3] > room_length - 0.05
                    or any(_overlap(box, _aabb(other), margin=0.03) for other in nonmembers)
                ):
                    valid = False
                    break
                boxes.append(box)
            if valid and all(
                not _overlap(boxes[left], boxes[right])
                for left in range(len(boxes))
                for right in range(left + 1, len(boxes))
            ):
                chosen = dx, dy
                break
        if chosen is not None:
            for member in members:
                member["x"] = float(member["x"]) + chosen[0]
                member["y"] = float(member["y"]) + chosen[1]
        else:
            for member in members:
                original = before[str(member["id"])]
                member["x"] = original["x"]
                member["y"] = original["y"]
                member["yaw"] = original["yaw"]

        after = {
            str(member["id"]): {
                "x": round(float(member.get("x", 0.0) or 0.0), 6),
                "y": round(float(member.get("y", 0.0) or 0.0), 6),
                "yaw": round(float(member.get("yaw", 0.0) or 0.0), 6),
            }
            for member in members
        }
        reports.append(
            {
                "group_id": group_id,
                "status": "adjusted" if chosen is not None else "no_collision_free_translation",
                "before": before,
                "after": after,
                "rigid_translation": (
                    {"dx": chosen[0], "dy": chosen[1]} if chosen is not None else None
                ),
                "member_respacing_applied": bool(
                    layout.get("allow_member_respacing", True)
                ),
                "shared_orientation_applied": bool(
                    layout.get("shared_orientation", True)
                ),
            }
        )
    report = {
        "schema": "codex_trellis_instance_group_postprocess_v1",
        "method": "bounded_member_spacing_then_rigid_translation",
        "group_count": len(groups),
        "adjusted_count": sum(item.get("status") == "adjusted" for item in reports),
        "results": reports,
    }
    plan["instance_group_resolution"] = report
    return report
