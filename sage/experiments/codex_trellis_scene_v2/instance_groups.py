from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any

from .orientation import AXIS_VECTORS, CARDINAL_YAWS, world_front_vector


GROUP_KINDS = {"paired_instances", "matched_set"}
ARRANGEMENTS = {"side_by_side", "mirrored_pair", "row"}
REFERENCE_FRAMES = {"room", "anchor_local"}
ANCHOR_ZONES = {"front", "near", "free"}
ASSET_MATCH_MODES = {"same_family", "same_asset"}
ASSET_FALLBACKS = {
    "same_asset_reuse",
    "shared_generation_spec",
    "mirror_primary",
    "reject",
}
HEADING_RULES = {"preserve", "anchor_front", "anchor_back"}
PAIR_ROLE_TO_HANDEDNESS = {
    "left_member": "left",
    "right_member": "right",
}
HANDEDNESS_ROLES = {"left", "right"}
CHIRAL_PAIR_CATEGORIES = {"slipper", "shoe", "glove"}


def member_handedness_role(member: dict[str, Any] | None) -> str:
    if not isinstance(member, dict):
        return ""
    return PAIR_ROLE_TO_HANDEDNESS.get(str(member.get("role") or ""), "")


def _opposite_handedness_role(role: str) -> str:
    return "right" if role == "left" else "left" if role == "right" else ""


def requires_handed_pair(group: dict[str, Any] | None) -> bool:
    if not isinstance(group, dict):
        return False
    contract = group.get("asset_contract")
    return bool(
        isinstance(contract, dict) and contract.get("requires_handedness", False)
    )


def _enforce_category_pair_policy(
    group: dict[str, Any], by_id: dict[str, dict[str, Any]]
) -> None:
    """Apply deterministic semantics that a model is not allowed to weaken."""

    member_rows = [
        member for member in group.get("members", []) if isinstance(member, dict)
    ]
    categories = {
        str(by_id.get(str(member.get("object_id") or ""), {}).get("category") or "")
        for member in member_rows
    }
    roles = {str(member.get("role") or "") for member in member_rows}
    if (
        len(categories) != 1
        or not categories <= CHIRAL_PAIR_CATEGORIES
        or roles != set(PAIR_ROLE_TO_HANDEDNESS)
    ):
        return
    asset_contract = group.setdefault("asset_contract", {})
    asset_contract.update(
        {
            "match_mode": "same_family",
            "fallback": "mirror_primary",
            "require_distinct_roles": True,
            "requires_handedness": True,
            "requires_medial_facing": True,
            "medial_facing_tolerance_degrees": 35.0,
            "mirror_axis": "lateral",
        }
    )
    layout_contract = group.setdefault("layout_contract", {})
    if layout_contract.get("anchor_id"):
        layout_contract["reference_frame"] = "anchor_local"
        layout_contract["heading_rule"] = "anchor_front"


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
    if fallback not in ASSET_FALLBACKS:
        return None, "unsupported asset fallback"
    mirror_axis = str(raw_asset.get("mirror_axis") or "lateral")
    if mirror_axis not in {"lateral", "x", "y"}:
        return None, "unsupported asset mirror_axis"

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
    heading_rule = str(raw_layout.get("heading_rule") or "preserve")
    if heading_rule not in HEADING_RULES:
        return None, "unsupported layout heading_rule"
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
                "requires_handedness": bool(
                    raw_asset.get("requires_handedness", False)
                ),
                "requires_medial_facing": bool(
                    raw_asset.get("requires_medial_facing", False)
                ),
                "medial_facing_tolerance_degrees": _number(
                    raw_asset.get("medial_facing_tolerance_degrees"),
                    35.0,
                    minimum=0.0,
                    maximum=90.0,
                ),
                "mirror_axis": mirror_axis,
            },
            "layout_contract": {
                "arrangement": arrangement,
                "reference_frame": reference_frame,
                "anchor_id": anchor_id or None,
                "anchor_zone": anchor_zone,
                "anchor_min_gap": anchor_min_gap,
                "anchor_target_gap": anchor_target_gap,
                "anchor_max_gap": anchor_max_gap,
                "heading_rule": heading_rule,
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
        chiral_pair = category in CHIRAL_PAIR_CATEGORIES
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
                "fallback": (
                    "mirror_primary" if chiral_pair else "same_asset_reuse"
                ),
                "require_distinct_roles": chiral_pair,
                "requires_handedness": chiral_pair,
                "requires_medial_facing": chiral_pair,
                "medial_facing_tolerance_degrees": 35.0,
                "mirror_axis": "lateral",
            },
            "layout_contract": {
                "arrangement": "side_by_side",
                "reference_frame": "room",
                "anchor_id": None,
                "anchor_zone": "free",
                "heading_rule": "preserve",
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
                    "reference_frame": "anchor_local",
                    "heading_rule": "anchor_front",
                }
            )
        canonical, reason = _canonical_group(
            raw,
            object_ids={str(obj["id"]) for obj in objects},
            prompt=prompt,
        )
        if canonical is not None and not reason:
            _enforce_category_pair_policy(
                canonical,
                {str(obj["id"]): obj for obj in objects if obj.get("id")},
            )
            result.append(canonical)
    return result


def recover_orphan_matched_groups(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Recover a legacy two-member matched-set contract from verified evidence.

    Recovery is deliberately narrow: both objects must already reference the same
    absent group, share a category and materialized asset, carry left/right member
    roles, and the prompt must contain an exact ``two matching <category>`` claim.
    """

    objects = [
        item
        for item in brief.get("objects", [])
        if isinstance(item, dict) and item.get("id")
    ]
    existing = {
        str(item.get("group_id"))
        for item in brief.get("instance_groups", [])
        if isinstance(item, dict) and item.get("group_id")
    }
    members_by_group: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        group_id = str(obj.get("instance_group_id") or "")
        if group_id and group_id not in existing:
            members_by_group.setdefault(group_id, []).append(obj)
    prompt = str(brief.get("original_prompt") or brief.get("description") or "")
    lowered = prompt.lower()
    recovered: list[dict[str, Any]] = []
    object_ids = {str(item["id"]) for item in objects}
    for group_id, members in sorted(members_by_group.items()):
        if len(members) != 2:
            continue
        categories = {str(item.get("category") or "") for item in members}
        asset_ids = {str(item.get("asset_id") or "") for item in members}
        roles = {str(item.get("instance_group_role") or "") for item in members}
        if len(categories) != 1 or len(asset_ids) != 1 or "" in asset_ids:
            continue
        if roles != {"left_member", "right_member"}:
            continue
        category = next(iter(categories))
        evidence_match = re.search(
            rf"(?:exactly\s+)?(?:two|2)\s+matching\s+{re.escape(category)}s?(?![a-z0-9])",
            lowered,
        )
        if evidence_match is None:
            continue
        gap = _rectangle_gap(members[0], members[1])
        if gap < 0.0 or gap > 2.0:
            continue
        raw = {
            "group_id": group_id,
            "group_kind": "matched_set",
            "cardinality": 2,
            "members": [
                {
                    "object_id": str(member["id"]),
                    "role": str(member["instance_group_role"]),
                }
                for member in members
            ],
            "asset_contract": {
                "match_mode": "same_asset",
                "fallback": "same_asset_reuse",
                "require_distinct_roles": False,
                "requires_handedness": False,
                "requires_medial_facing": False,
                "mirror_axis": "lateral",
            },
            "layout_contract": {
                "arrangement": "side_by_side",
                "reference_frame": "room",
                "anchor_id": None,
                "anchor_zone": "free",
                "heading_rule": "preserve",
                "shared_orientation": True,
                "orientation_tolerance_degrees": 15.0,
                "min_gap": max(0.0, gap - 0.10),
                "target_gap": gap,
                "max_gap": min(2.0, gap + 0.10),
                "allow_member_respacing": False,
                "allow_rigid_translation": False,
            },
            "source_evidence": prompt[evidence_match.start() : evidence_match.end()],
            "provenance": "legacy_orphan_matched_group_recovery",
        }
        canonical, reason = _canonical_group(
            raw, object_ids=object_ids, prompt=prompt
        )
        if canonical is not None and not reason:
            recovered.append(canonical)
    brief.setdefault("instance_groups", []).extend(recovered)
    return recovered


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
    by_id = {
        str(obj["id"]): obj
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
        _enforce_category_pair_policy(canonical, by_id)
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
            if requires_handed_pair(baseline):
                baseline_roles = {
                    str(member.get("object_id") or ""): str(
                        member.get("role") or ""
                    )
                    for member in baseline.get("members", [])
                    if isinstance(member, dict)
                }
                for member in canonical.get("members", []):
                    object_id = str(member.get("object_id") or "")
                    if object_id in baseline_roles:
                        member["role"] = baseline_roles[object_id]
                baseline_layout = baseline.get("layout_contract")
                baseline_layout = (
                    baseline_layout if isinstance(baseline_layout, dict) else {}
                )
                if baseline_layout.get("anchor_id"):
                    for key in (
                        "reference_frame",
                        "anchor_id",
                        "anchor_zone",
                        "anchor_min_gap",
                        "anchor_target_gap",
                        "anchor_max_gap",
                        "heading_rule",
                    ):
                        canonical["layout_contract"][key] = deepcopy(
                            baseline_layout.get(key)
                        )
            _enforce_category_pair_policy(canonical, by_id)
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


def _is_materialized_asset(obj: dict[str, Any]) -> bool:
    return str(obj.get("asset_source") or "") not in {
        "",
        "missing_generation_plan",
    }


def _reference_front(
    layout: dict[str, Any],
    members: list[dict[str, Any]],
    anchor: dict[str, Any] | None,
) -> tuple[float, float]:
    heading_rule = str(layout.get("heading_rule") or "preserve")
    if anchor is not None and heading_rule in {"anchor_front", "anchor_back"}:
        front = world_front_vector(anchor)
        return front if heading_rule == "anchor_front" else (-front[0], -front[1])
    return world_front_vector(members[0])


def _resolved_reflection_axis(
    contract: dict[str, Any], source_member: dict[str, Any]
) -> str:
    requested = str(contract.get("mirror_axis") or "lateral")
    if requested in {"x", "y"}:
        return requested
    front = source_member.get("asset_canonical_front")
    front = front if isinstance(front, dict) else {}
    front_axis = str(front.get("axis") or "+y").lower().lstrip("+-")
    return "y" if front_axis == "x" else "x"


def _world_medial_vector(member: dict[str, Any]) -> tuple[float, float] | None:
    """Transform an audited source-mesh medial axis into world space."""

    raw = member.get("asset_medial_axis")
    raw = raw if isinstance(raw, dict) else {}
    axis = str(raw.get("axis") or "").lower()
    if axis not in AXIS_VECTORS:
        return None
    vector = AXIS_VECTORS[axis]
    reflection_axis = str(member.get("asset_reflection_axis") or "")
    if reflection_axis == "x":
        vector = (-vector[0], vector[1])
    elif reflection_axis == "y":
        vector = (vector[0], -vector[1])
    elif reflection_axis:
        return None
    rotation = (
        float(member.get("yaw", 0.0) or 0.0)
        + float(member.get("footprint_yaw_offset_degrees", 0.0) or 0.0)
        + float(member.get("asset_local_yaw_offset_degrees", 0.0) or 0.0)
    )
    angle = math.radians(rotation)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        vector[0] * cosine - vector[1] * sine,
        vector[0] * sine + vector[1] * cosine,
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
        anchor_id = str(layout.get("anchor_id") or "")
        anchor_zone = str(layout.get("anchor_zone") or "free")
        anchor = by_id.get(anchor_id)
        reference_front = _reference_front(layout, members, anchor)
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
                front = reference_front
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

        anchor_orientation_errors: list[float] = []
        anchor_orientation_ok = True
        if (
            anchor is not None
            and str(layout.get("heading_rule") or "preserve")
            in {"anchor_front", "anchor_back"}
        ):
            anchor_orientation_errors = [
                _angle_error(world_front_vector(member), reference_front)
                for member in members
            ]
            tolerance = float(
                layout.get("orientation_tolerance_degrees", 15.0) or 15.0
            )
            anchor_orientation_ok = all(
                error <= tolerance + 1e-6 for error in anchor_orientation_errors
            )
            if not anchor_orientation_ok:
                violations.append(
                    {
                        "type": "instance_group_anchor_orientation",
                        "severity": "hard",
                        "group_id": group_id,
                        "anchor_id": anchor_id,
                        "heading_rule": str(layout.get("heading_rule")),
                        "member_ids": member_ids,
                        "angle_errors_degrees": [
                            round(error, 6) for error in anchor_orientation_errors
                        ],
                        "tolerance_degrees": tolerance,
                    }
                )

        asset_keys = [_group_asset_key(member) for member in members]
        resolved_assets = all(_is_materialized_asset(member) for member in members)
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
        source_handedness = [
            str(member.get("asset_source_pair_role") or "") for member in members
        ]
        asset_contract = group.get("asset_contract")
        asset_contract = asset_contract if isinstance(asset_contract, dict) else {}
        expected_handedness = [member_handedness_role(row) for row in member_rows]
        roles_aligned = bool(expected_handedness) and all(
            expected and expected == actual
            for expected, actual in zip(expected_handedness, handedness)
        )
        asset_ids = [str(member.get("asset_id") or "") for member in members]
        reflection_axes = [
            str(member.get("asset_reflection_axis") or "") for member in members
        ]
        geometry_handedness = [
            (
                _opposite_handedness_role(source_role)
                if reflection_axis
                else source_role
            )
            if source_role in HANDEDNESS_ROLES
            else ""
            for source_role, reflection_axis in zip(
                source_handedness, reflection_axes
            )
        ]
        source_roles_verified = bool(source_handedness) and all(
            role in HANDEDNESS_ROLES for role in source_handedness
        )
        geometry_roles_aligned = source_roles_verified and all(
            geometry_role == actual_role == expected_role
            for geometry_role, actual_role, expected_role in zip(
                geometry_handedness, handedness, expected_handedness
            )
        )
        expected_reflection_axis = _resolved_reflection_axis(
            asset_contract, members[0]
        )
        distinct_manifest_pair = (
            len(set(asset_ids) - {""}) == len(members)
            and len(set(handedness) - {""}) == len(members)
        )
        mirrored_pair = (
            len(set(asset_ids) - {""}) == 1
            and sum(bool(axis) for axis in reflection_axes) == 1
            and all(
                axis in {"", expected_reflection_axis} for axis in reflection_axes
            )
        )
        handedness_verified = roles_aligned and geometry_roles_aligned and (
            distinct_manifest_pair or mirrored_pair
        )
        handedness_required = bool(asset_contract.get("requires_handedness", False))
        handedness_ok = not resolved_assets or not handedness_required or handedness_verified
        if (
            resolved_assets
            and bool(asset_contract.get("require_distinct_roles", False))
            and not handedness_verified
        ):
            violations.append(
                {
                    "type": "instance_group_handedness_unverified",
                    "severity": "hard" if handedness_required else "soft",
                    "group_id": group_id,
                    "member_ids": member_ids,
                    "expected_pair_roles": expected_handedness,
                    "actual_pair_roles": handedness,
                    "source_pair_roles": source_handedness,
                    "geometry_pair_roles_after_reflection": geometry_handedness,
                    "asset_ids": asset_ids,
                    "reflection_axes": reflection_axes,
                    "expected_reflection_axis": expected_reflection_axis,
                    "reason": "anatomical source roles, reflection parity, and member roles must agree for either a manifest pair or one verified local reflection",
                }
            )

        medial_scores: list[float | None] = []
        medial_facing_verified = True
        medial_facing_required = bool(
            asset_contract.get("requires_medial_facing", False)
        )
        if resolved_assets and medial_facing_required:
            tolerance = float(
                asset_contract.get("medial_facing_tolerance_degrees", 35.0)
                or 35.0
            )
            minimum_score = math.cos(math.radians(tolerance))
            for index, member in enumerate(members):
                medial = _world_medial_vector(member)
                others = [
                    other for other_index, other in enumerate(members)
                    if other_index != index
                ]
                target_x = sum(float(other.get("x", 0.0) or 0.0) for other in others) / len(others)
                target_y = sum(float(other.get("y", 0.0) or 0.0) for other in others) / len(others)
                dx = target_x - float(member.get("x", 0.0) or 0.0)
                dy = target_y - float(member.get("y", 0.0) or 0.0)
                distance = math.hypot(dx, dy)
                if medial is None or distance <= 1e-9:
                    medial_scores.append(None)
                    continue
                medial_scores.append(
                    medial[0] * dx / distance + medial[1] * dy / distance
                )
            medial_facing_verified = len(medial_scores) == len(members) and all(
                score is not None and score >= minimum_score - 1e-6
                for score in medial_scores
            )
            if not medial_facing_verified:
                violations.append(
                    {
                        "type": "instance_group_medial_facing",
                        "severity": "hard",
                        "group_id": group_id,
                        "member_ids": member_ids,
                        "source_pair_roles": source_handedness,
                        "reflection_axes": reflection_axes,
                        "medial_facing_scores": [
                            round(score, 6) if score is not None else None
                            for score in medial_scores
                        ],
                        "minimum_score": round(minimum_score, 6),
                        "tolerance_degrees": tolerance,
                        "reason": "each audited anatomical medial side must point toward the other member",
                    }
                )
        medial_facing_ok = (
            not resolved_assets
            or not medial_facing_required
            or medial_facing_verified
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
                "anchor_orientation_ok": anchor_orientation_ok,
                "asset_match_ok": asset_match_ok,
                "handedness_verified": handedness_verified,
                "handedness_ok": handedness_ok,
                "source_pair_roles": source_handedness,
                "geometry_pair_roles_after_reflection": geometry_handedness,
                "medial_facing_verified": medial_facing_verified,
                "medial_facing_ok": medial_facing_ok,
                "medial_facing_scores": [
                    round(score, 6) if score is not None else None
                    for score in medial_scores
                ],
                "gaps": [round(gap, 6) for gap in gaps],
                "orientation_errors_degrees": [
                    round(error, 6) for error in orientation_errors
                ],
                "anchor_orientation_errors_degrees": [
                    round(error, 6) for error in anchor_orientation_errors
                ],
                "ok": (
                    spacing_ok
                    and arrangement_ok
                    and anchor_ok
                    and orientation_ok
                    and anchor_orientation_ok
                    and asset_match_ok
                    and handedness_ok
                    and medial_facing_ok
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
        anchor_id = str(layout.get("anchor_id") or "")
        anchor = by_id.get(anchor_id)
        expected_front = _reference_front(layout, members, anchor)
        facing_sources = {
            str(relation.get("source") or "")
            for relation in plan.get("relations", [])
            if isinstance(relation, dict)
            and str(relation.get("type") or "") in {"faces", "facing"}
        }
        if bool(layout.get("shared_orientation", True)):
            heading_rule = str(layout.get("heading_rule") or "preserve")
            orientation_members = (
                members
                if anchor is not None
                and heading_rule in {"anchor_front", "anchor_back"}
                else members[1:]
            )
            for member in orientation_members:
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

        # Thin floor coverings are support/decor surfaces, not solid obstacles.
        # Treating a rug as a blocking furniture box pushes slippers and other
        # matched floor sets away from their semantic anchor even though they
        # are expected to rest on or overlap the rug footprint.
        nonblocking_floor_categories = {
            "area_rug",
            "rug",
            "carpet",
            "floor_mat",
            "doormat",
        }
        nonmembers = [
            obj
            for obj in objects
            if obj not in members
            and str(obj.get("category") or "") not in nonblocking_floor_categories
        ]
        candidate_translations: list[tuple[float, float]] = []
        anchor_zone = str(layout.get("anchor_zone") or "free")
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
