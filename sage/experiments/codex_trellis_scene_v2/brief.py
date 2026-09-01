from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from .asset_admission import build_count_contract
from .composition import camera_requirements_from_prompt, render_requirements_from_prompt
from .constraint_scopes import ground_constraint_scopes
from .dimensions import dimension_policy_for_category
from .instance_groups import (
    deterministic_pair_groups,
    ground_instance_groups,
)
from .io_utils import run_codex_json
from .policies import (
    COMPOSITE_COMPONENT_POLICIES,
    FUNCTIONAL_FRONT_CLEARANCE,
    OBJECT_DEFINITIONS,
    detect_explicit_category_counts,
    detect_grouped_component_count_contracts,
    detect_room_type,
    detect_styles,
    room_policy,
)


GROUNDING_RELATION_ALIASES = {
    "on": "supported_by",
    "against": "against_wall",
    "facing": "faces",
}

GROUNDING_RELATION_TYPES = {
    "supported_by",
    "tucked_under",
    "against_wall",
    "faces",
    "left_of",
    "right_of",
    "in_front_of",
    "separated_from",
    "clearance_from",
    "aligned_with",
    "mirror_symmetric",
}

WALL_NODE_IDS = {f"{wall}_wall" for wall in ("north", "south", "east", "west")}

DEFAULT_SUPPORT_OFFSETS = {
    ("book_stack", "desk"): [-0.38, 0.0],
    ("mug", "desk"): [0.38, 0.0],
}

DEFAULT_TUCKED_UNDER_FREE_SPACES = {
    ("office_chair", "desk"): "under_desk",
}


ASSET_SHAPE_GUIDANCE = {
    "book_stack": "one compact stack of several closed books with distinct covers and page blocks",
    "bookcase": "one freestanding open-front bookcase with two vertical side supports and several repeated horizontal shelves and visible storage cavities",
    "storage_box": "one closed rectangular fabric-covered storage box with straight edges and a visible lid",
    "accent_chair": "one complete accent chair with a distinct seat, backrest, arm or side supports, and stable separated legs",
    "dining_chair": "one complete dining chair with a distinct seat, upright backrest, and stable separated legs",
    "office_chair": "one complete office chair with a distinct seat, backrest, central support, and stable wheeled or legged base",
    "table_lamp": "one complete table lamp with a distinct shade, central stem or body, and integrated stable base",
    "floor_lamp": "one complete tall floor lamp with a distinct shade or light head, slender stem, and integrated stable base",
    "potted_plant": "one complete potted plant with an actual plant pot, visible stems, and naturally branching leaves",
    "pillow": "one soft rectangular sleeping pillow with rounded corners, fabric seams, and a gently puffed form",
    "slipper": "one open-back slide house slipper with a clear sole, broad upper strap, exposed heel end, and left-or-right form",
    "mug": "one ceramic drinking mug with a clearly separated handle and open top",
}


ASSET_SEMANTIC_FORM_HINTS: dict[str, dict[str, Any]] = {
    "storage_box": {
        "shape_profile": "compact_orthogonal",
        "required_parts": ["closed box body", "visible lid"],
        "forbidden_parts": ["display pedestal", "extra floor platform"],
        "hard_negative_identities": ["ottoman", "suitcase", "cabinet", "open basket"],
    },
    "bookcase": {
        "shape_profile": "open_repeated_frame",
        "required_parts": ["open front", "multiple horizontal shelves", "vertical side supports"],
        "forbidden_parts": ["closed solid doors", "display pedestal"],
        "hard_negative_identities": ["closed wardrobe", "solid cabinet", "ladder", "wall panel"],
    },
    "book_stack": {
        "identity": "stack of closed books",
        "shape_profile": "compact_layered",
        "required_parts": ["multiple distinct book layers", "visible covers and page blocks"],
        "forbidden_parts": ["bookcase", "display pedestal"],
        "hard_negative_identities": ["single box", "bookcase", "loose paper pile"],
    },
    "accent_chair": {
        "shape_profile": "skeletal_support",
        "required_parts": ["seat", "backrest", "stable support legs"],
        "forbidden_parts": ["display pedestal"],
        "hard_negative_identities": ["stool", "sofa", "side table"],
    },
    "dining_chair": {
        "shape_profile": "skeletal_support",
        "required_parts": ["seat", "upright backrest", "stable support legs"],
        "forbidden_parts": ["display pedestal"],
        "hard_negative_identities": ["stool", "armchair", "side table"],
    },
    "office_chair": {
        "shape_profile": "skeletal_support",
        "required_parts": ["seat", "backrest", "stable central or separated support"],
        "forbidden_parts": ["display pedestal"],
        "hard_negative_identities": ["stool", "dining chair", "side table"],
    },
    "table_lamp": {
        "shape_profile": "slender_radial",
        "required_parts": ["light shade or light head", "central body", "integrated base"],
        "forbidden_parts": ["extra floor platform"],
        "hard_negative_identities": ["vase", "floor lamp", "candle holder"],
    },
    "floor_lamp": {
        "shape_profile": "slender_radial",
        "required_parts": ["light shade or light head", "tall stem", "integrated base"],
        "forbidden_parts": ["extra floor platform"],
        "hard_negative_identities": ["table lamp", "coat rack", "plant stand"],
    },
    "potted_plant": {
        "shape_profile": "organic_branching",
        "required_parts": ["actual plant pot", "stems", "branching leaves"],
        "forbidden_parts": ["extra saucer platform", "display pedestal"],
        "hard_negative_identities": ["vase of flowers", "artificial tree sculpture", "empty pot"],
    },
    "slipper": {
        "shape_profile": "open_back_footwear",
        "required_parts": [
            "sole",
            "broad upper strap",
            "open back with an exposed heel end",
            "left-or-right anatomical shape",
        ],
        "forbidden_parts": ["duplicate pair", "display pedestal"],
        "hard_negative_identities": [
            "closed-back shoe",
            "closed-back loafer",
            "moccasin",
            "sock",
            "sandal pair",
        ],
        "semantic_gate": {
            "minimum_category_margin": 0.55,
            "minimum_required_part_score": 0.04,
            "maximum_forbidden_probability": 0.60,
        },
    },
}

ASSET_APPEARANCE_TERMS = {
    "white": ("white", "白色"),
    "black": ("black", "黑色"),
    "light gray": ("light gray", "light grey", "浅灰"),
    "gray": ("gray", "grey", "灰色"),
    "beige": ("beige", "米色"),
    "navy blue": ("navy", "深蓝"),
    "blue": ("blue", "蓝色"),
    "green": ("green", "绿色"),
    "red": ("red", "红色"),
    "natural oak": ("oak", "橡木"),
    "dark walnut": ("walnut", "胡桃木"),
    "natural wood": ("wooden", "wood", "原木", "木质"),
    "woven fabric": ("woven fabric", "fabric", "linen", "velvet", "布艺", "织物", "亚麻", "天鹅绒"),
    "leather": ("leather", "皮革"),
    "matte metal": ("metal", "metallic", "金属"),
    "ceramic": ("ceramic", "陶瓷"),
    "clear glass": ("glass", "玻璃"),
    "matte plastic": ("plastic", "polymer", "塑料"),
}


def _prompt_segments(prompt: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\n.!?。！？;；]+", prompt) if part.strip()]


def _contains_prompt_term(text: str, term: str) -> bool:
    lowered_term = term.lower()
    if re.search(r"[a-z]", lowered_term):
        return bool(
            re.search(rf"(?<![a-z]){re.escape(lowered_term)}(?![a-z])", text.lower())
        )
    return lowered_term in text.lower()


def _asset_style_tags(styles: list[str], original_prompt: str) -> list[str]:
    lowered = original_prompt.lower()
    explicit_minimal_style = any(
        phrase in lowered
        for phrase in (
            "minimalist",
            "minimal design",
            "minimal style",
            "minimal interior",
            "minimal room",
            "极简",
            "简约",
        )
    )
    return [
        str(style)
        for style in styles
        if str(style).strip() and (style != "minimal" or explicit_minimal_style)
    ][:6]


def category_appearance_terms(category: str, original_prompt: str) -> list[str]:
    definition = OBJECT_DEFINITIONS[category]
    labels = [category.replace("_", " "), *definition.get("keywords", [])]
    relevant = [
        segment.lower()
        for segment in _prompt_segments(original_prompt)
        if any(_contains_prompt_term(segment, str(label)) for label in labels)
    ]
    evidence = " ".join(relevant)
    return [
        canonical
        for canonical, variants in ASSET_APPEARANCE_TERMS.items()
        if any(_contains_prompt_term(evidence, variant) for variant in variants)
    ][:4]


# Compatibility alias for older internal call sites and downstream experiments.
_category_appearance_terms = category_appearance_terms


def build_asset_generation_spec(
    obj: dict[str, Any], styles: list[str], original_prompt: str
) -> dict[str, Any]:
    """Derive a bounded single-object description without copying room context."""

    category = str(obj["category"])
    dimensions = deepcopy(obj.get("requested_dimensions") or obj.get("dimensions"))
    width = float(dimensions["width"])
    length = float(dimensions["length"])
    height = float(dimensions["height"])
    shortest = max(0.001, min(width, length, height))
    ratios = [round(value / shortest, 2) for value in (width, length, height)]
    component_requirements = [
        {
            key: deepcopy(requirement.get(key))
            for key in (
                "category",
                "requested_count",
                "mode",
                "appearance_terms",
                "source",
            )
            if key in requirement
        }
        for requirement in obj.get("component_requirements", [])
        if isinstance(requirement, dict)
    ]
    grounded_appearance = obj.get("appearance_terms_grounded")
    appearance_terms = (
        [str(item) for item in grounded_appearance if str(item).strip()][:6]
        if isinstance(grounded_appearance, list)
        else category_appearance_terms(category, original_prompt)
    )
    semantic_form = deepcopy(ASSET_SEMANTIC_FORM_HINTS.get(category, {}))
    semantic_form.setdefault("identity", category.replace("_", " "))
    semantic_form.setdefault("shape_profile", "general_object")
    semantic_form.setdefault("required_parts", [])
    semantic_form.setdefault("forbidden_parts", ["display pedestal", "extra prop"])
    semantic_form.setdefault("hard_negative_identities", [])
    semantic_form.update(
        {
            "schema": "scene_dna_semantic_form_contract_v1",
            "target_proportion_ratio_w_l_h": ratios,
            "source": "asset_semantic_form_registry_and_requested_dimensions",
        }
    )
    raw_count_contract = obj.get("count_contract")
    count_contract = None
    if isinstance(raw_count_contract, dict):
        count_contract = build_count_contract(
            component_category=str(
                raw_count_contract.get("component_category") or category
            ),
            expected_count=int(raw_count_contract.get("expected_count", 0) or 0),
            arrangement=str(raw_count_contract.get("arrangement") or "single_row"),
        )
    return {
        "schema": "codex_trellis_single_asset_spec_v1",
        "category": category,
        "object_label": category.replace("_", " "),
        "shape_guidance": ASSET_SHAPE_GUIDANCE.get(
            category, f"one complete, plausible {category.replace('_', ' ')}"
        ),
        "semantic_form_contract": semantic_form,
        "style_tags": _asset_style_tags(styles, original_prompt),
        "appearance_terms": appearance_terms,
        "target_dimensions_m": {
            "width": width,
            "length": length,
            "height": height,
        },
        "target_proportion_ratio_w_l_h": ratios,
        "dimension_handling": "metadata_for_post_generation_adaptation",
        "integrated_component_requirements": component_requirements,
        "count_contract": count_contract,
        "source_requirements": {
            "scene_prompt_used_for": [
                "category",
                "style_tags",
                "category_local_appearance_terms",
                "integrated_component_count_and_appearance",
            ],
            "full_scene_prompt_forwarded": False,
            "object_provenance": str(obj.get("provenance") or "unspecified"),
        },
    }


def render_asset_prompt(spec: dict[str, Any]) -> str:
    styles = ", ".join(spec.get("style_tags", [])) or "clean realistic"
    appearance = ", ".join(spec.get("appearance_terms", []))
    ratios = spec["target_proportion_ratio_w_l_h"]
    clauses = [
        str(spec["shape_guidance"]),
        f"{styles} design",
    ]
    if appearance:
        clauses.append(appearance)
    count_contract = spec.get("count_contract")
    if isinstance(count_contract, dict):
        expected = int(count_contract["expected_count"])
        component = str(count_contract["component_category"]).replace("_", " ")
        clauses.append(
            f"exactly {expected} distinct {component}{'s' if expected != 1 else ''} "
            f"in one {str(count_contract['arrangement']).replace('_', ' ')}; "
            "the same complete group must be visible from front and back; "
            "side views must show no second row or hidden duplicate group"
        )
    for requirement in spec.get("integrated_component_requirements", []):
        if not isinstance(requirement, dict):
            continue
        category = str(requirement.get("category") or "component").replace("_", " ")
        count = max(1, int(requirement.get("requested_count", 1)))
        component_appearance = ", ".join(requirement.get("appearance_terms", []))
        component_clause = (
            f"the complete composite asset includes {count} integrated {category}"
            f"{'s' if count != 1 else ''}"
        )
        if component_appearance:
            component_clause += f" in {component_appearance}"
        clauses.append(component_clause + ", not separate floating objects")
    clauses.extend(
        [
            "realistic moderate material detail and clean geometry",
            f"visual width:length:height proportions about {ratios[0]}:{ratios[1]}:{ratios[2]}",
            "complete object visible in a centered three-quarter product view",
            "uniform bright diffuse lighting on a plain contrasting background",
            "isolated object only; no room, surrounding furniture, extra props, text, platform, or ground plane",
        ]
    )
    if str(spec.get("category") or "") in {"floor_lamp", "table_lamp"}:
        clauses.append(
            "no visible power cord, loose cable, plug, or wire extending from the lamp"
        )
    return ". ".join(clauses) + "."


def _asset_inventory(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        grouped.setdefault(str(obj["category"]), []).append(obj)
    return [
        {
            "category": category,
            "requested_count": len(items),
            "required_count": sum(bool(item.get("required", True)) for item in items),
            "instance_ids": [str(item["id"]) for item in items],
        }
        for category, items in grouped.items()
    ]


def _absorb_integrated_components(
    objects: list[dict[str, Any]], prompt: str
) -> list[dict[str, Any]]:
    resolutions: list[dict[str, Any]] = []
    remove_ids: set[str] = set()
    for parent_category, policy in COMPOSITE_COMPONENT_POLICIES.items():
        parents = [
            obj for obj in objects if str(obj.get("category")) == parent_category
        ]
        for component_category in policy.get("absorbs_categories", []):
            components = [
                obj
                for obj in objects
                if str(obj.get("category")) == str(component_category)
            ]
            if not components:
                continue
            if bool(policy.get("require_single_parent_instance")) and len(parents) != 1:
                resolutions.append(
                    {
                        "parent_category": parent_category,
                        "component_category": str(component_category),
                        "requested_count": len(components),
                        "action": "retained_as_standalone",
                        "reason": "integrated component absorption requires exactly one parent instance",
                        "candidate_parent_ids": [str(parent["id"]) for parent in parents],
                        "standalone_instance_ids": [str(obj["id"]) for obj in components],
                    }
                )
                continue
            if not parents:
                continue
            parent = parents[0]
            absorbed_ids = [str(obj["id"]) for obj in components]
            requirement = {
                "category": str(component_category),
                "requested_count": len(components),
                "mode": str(policy.get("mode") or "integrated"),
                "source": sorted(
                    {
                        str(obj.get("provenance") or "unspecified")
                        for obj in components
                    }
                ),
                "appearance_terms": _category_appearance_terms(
                    str(component_category), prompt
                ),
                "absorbed_instance_ids": absorbed_ids,
                "physical_instances_materialized": False,
                "resolution_status": "pending_asset_resolution",
            }
            parent.setdefault("component_requirements", []).append(requirement)
            parent["component_policy"] = {
                "mode": str(policy.get("mode") or "integrated"),
                "absorbs_categories": [
                    str(category) for category in policy.get("absorbs_categories", [])
                ],
                "curated_asset_fallback": str(
                    policy.get("curated_asset_fallback") or "unspecified"
                ),
            }
            remove_ids.update(absorbed_ids)
            resolutions.append(
                {
                    "parent_id": str(parent["id"]),
                    "parent_category": parent_category,
                    "component_category": str(component_category),
                    "requested_count": len(components),
                    "appearance_terms": deepcopy(requirement["appearance_terms"]),
                    "action": "absorbed_into_composite_asset",
                    "standalone_instances_removed": absorbed_ids,
                    "physical_instances_materialized": False,
                    "resolution_status": "pending_asset_resolution",
                }
            )
    if remove_ids:
        objects[:] = [obj for obj in objects if str(obj.get("id")) not in remove_ids]
    return resolutions


def _included_component_count(parent: dict[str, Any], category: str) -> int | None:
    included = parent.get("included_components")
    if isinstance(included, dict):
        value = included.get(category)
        if isinstance(value, dict):
            value = value.get("count")
        if isinstance(value, (int, float)):
            return int(value)
    if isinstance(included, list):
        count = 0
        found = False
        for item in included:
            if isinstance(item, str) and item == category:
                count += 1
                found = True
            elif isinstance(item, dict) and str(item.get("category")) == category:
                count += int(item.get("count", 1))
                found = True
        return count if found else None
    return None


def finalize_integrated_component_resolution(brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Record how a selected/generated composite asset satisfies absorbed requests."""

    objects = {
        str(obj["id"]): obj
        for obj in brief.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }
    for row in brief.get("component_resolution", []):
        if not isinstance(row, dict) or row.get("action") != "absorbed_into_composite_asset":
            continue
        parent = objects.get(str(row.get("parent_id") or ""))
        if parent is None:
            row["resolution_status"] = "parent_missing_after_asset_resolution"
            continue
        category = str(row.get("component_category") or "")
        requested_count = int(row.get("requested_count", 0))
        included_count = _included_component_count(parent, category)
        asset_source = str(parent.get("asset_source") or "")
        if included_count is not None:
            status = (
                "verified_by_asset_manifest"
                if included_count >= requested_count
                else "asset_manifest_component_shortfall"
            )
        elif asset_source == "curated_library":
            status = "assumed_satisfied_by_composite_asset"
        elif asset_source in {
            "trellis2_staging",
            "trellis2_generated_instance_reuse",
            "missing_generation_plan",
        }:
            status = "requested_in_composite_asset_prompt"
        else:
            status = "pending_asset_resolution"
        row.update(
            {
                "resolution_status": status,
                "parent_asset_id": parent.get("asset_id"),
                "parent_asset_source": parent.get("asset_source"),
                "manifest_included_count": included_count,
            }
        )
        for requirement in parent.get("component_requirements", []):
            if isinstance(requirement, dict) and str(requirement.get("category")) == category:
                requirement.update(
                    {
                        "resolution_status": status,
                        "parent_asset_id": parent.get("asset_id"),
                        "parent_asset_source": parent.get("asset_source"),
                        "manifest_included_count": included_count,
                    }
                )
    return brief.get("component_resolution", [])


def _relation_parts(item: Any) -> tuple[str, str, str] | None:
    if isinstance(item, (list, tuple)) and len(item) == 3:
        source, relation_type, target = (str(value) for value in item)
    elif isinstance(item, dict):
        source = str(item.get("source") or item.get("subject") or "")
        relation_type = str(item.get("type") or item.get("predicate") or "")
        target = str(item.get("target") or item.get("object") or "")
    else:
        return None
    relation_type = GROUNDING_RELATION_ALIASES.get(relation_type, relation_type)
    return source, relation_type, target


def _remove_conflicting_relations(
    relations: list[Any], source: str, relation_type: str
) -> list[Any]:
    result = []
    for item in relations:
        parts = _relation_parts(item)
        if parts and parts[0] == source and parts[1] == relation_type:
            continue
        result.append(item)
    return result


def _locked_side_role(
    relations: list[Any], source: str, target: str
) -> dict[str, Any] | None:
    """Return an explicit baseline side role without interpreting entity ids."""

    for item in relations:
        parts = _relation_parts(item)
        if not parts or parts[0] != source or parts[2] != target:
            continue
        if parts[1] not in {"left_of", "right_of"} or not isinstance(item, dict):
            continue
        parameters = item.get("parameters")
        if not isinstance(parameters, dict) or parameters.get("role_locked") is not True:
            continue
        side_role = str(parameters.get("side_role") or "")
        if side_role not in {"left", "right"}:
            continue
        role_frame = str(
            parameters.get("role_reference_frame")
            or parameters.get("reference_frame")
            or "room"
        )
        if role_frame not in {"room", "target_local"}:
            role_frame = "room"
        return {
            "side_role": side_role,
            "relation_type": f"{side_role}_of",
            "reference_frame": role_frame,
            "role_source": str(parameters.get("role_source") or "baseline"),
        }
    return None


def _remove_relation_edge(
    relations: list[Any], source: str, relation_type: str, target: str
) -> list[Any]:
    return [
        item
        for item in relations
        if _relation_parts(item) != (source, relation_type, target)
    ]


def _explicit_reference_frame_evidence(evidence: str, original_prompt: str) -> bool:
    """Accept a frame override only when the cited prompt fragment names a viewpoint."""

    evidence = " ".join(evidence.lower().split())
    prompt = " ".join(original_prompt.lower().split())
    if not evidence or evidence not in prompt:
        return False
    patterns = (
        r"\bfrom (?:the )?.{0,50}(?:perspective|viewpoint|point of view)\b",
        r"\brelative to .{0,50}(?:orientation|local frame|facing direction)\b",
        r"\b(?:camera|screen|viewer(?:'s)?|room) (?:left|right)\b",
        r"\b(?:east|west) side\b",
        r"从.{0,30}(?:视角|角度)看",
        r"以.{0,30}(?:朝向|局部坐标|参考系)为参照",
        r"(?:相机|画面|观察者|房间)(?:的)?(?:左|右)侧?",
        r"(?:东|西)侧",
    )
    return any(re.search(pattern, evidence) for pattern in patterns)


def _explicit_tucked_under_evidence(
    evidence: str, original_prompt: str
) -> bool:
    """Require an exact prompt fragment before upgrading a spatial relation."""

    evidence = " ".join(evidence.lower().split())
    prompt = " ".join(original_prompt.lower().split())
    if not evidence or evidence not in prompt:
        return False
    patterns = (
        (
            r"\b(?:tuck(?:ed|ing)?|push(?:ed|ing)?|slide|slid|sliding|"
            r"place(?:d|ing)?|store(?:d|ing)?)\b.{0,80}\b(?:under|beneath)\b"
        ),
        r"\b(?:under|beneath) (?:the )?(?:desk|table|workstation)\b",
        r"(?:塞|收|推|滑|放|置).{0,30}(?:桌|台|工作台).{0,8}(?:下|下方|底下)",
        r"(?:桌|台|工作台)(?:下|下方|底下).{0,30}(?:椅|座椅)",
    )
    return any(re.search(pattern, evidence) for pattern in patterns)


def _support_cycle(
    objects_by_id: dict[str, dict[str, Any]], source: str, target: str
) -> bool:
    current = target
    visited: set[str] = set()
    while current and current not in visited:
        if current == source:
            return True
        visited.add(current)
        parent = objects_by_id.get(current, {}).get("support_id")
        current = str(parent or "")
    return False


def _wall_facing_constraint(obj: dict[str, Any], wall: str) -> dict[str, Any] | None:
    clearance = FUNCTIONAL_FRONT_CLEARANCE.get(str(obj.get("category") or ""))
    if clearance is None:
        return None
    existing = obj.get("facing_constraint")
    existing = deepcopy(existing) if isinstance(existing, dict) else {}
    existing.update(
        {
            "mode": "into_room",
            "wall": wall,
            "contact_face": "back",
            "primary_interaction_face": "front",
            "local_front_fallback": str(
                existing.get("local_front_fallback") or "-y"
            ),
            "tolerance_degrees": float(
                existing.get("tolerance_degrees", 15.0) or 15.0
            ),
            "front_clearance_depth": float(clearance),
        }
    )
    return existing


def apply_expansion_grounding(
    brief: dict[str, Any], expanded: dict[str, Any]
) -> dict[str, Any]:
    """Validate and merge Codex semantic deltas into the canonical SceneBrief."""

    objects = [obj for obj in brief.get("objects", []) if isinstance(obj, dict)]
    objects_by_id = {
        str(obj["id"]): obj for obj in objects if str(obj.get("id") or "")
    }
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    normalizations: list[dict[str, Any]] = []
    relations = list(brief.get("relations", []))
    original_prompt = str(brief.get("original_prompt") or "")

    raw_updates = expanded.get("relation_updates", [])
    if not isinstance(raw_updates, list):
        raw_updates = []
        rejected.append(
            {
                "update_kind": "relation",
                "reason": "relation_updates must be a list",
            }
        )
    for raw in raw_updates[:64]:
        if not isinstance(raw, dict):
            rejected.append(
                {"update_kind": "relation", "raw": deepcopy(raw), "reason": "not an object"}
            )
            continue
        source = str(raw.get("source") or "")
        target = str(raw.get("target") or "")
        relation_type = GROUNDING_RELATION_ALIASES.get(
            str(raw.get("type") or ""), str(raw.get("type") or "")
        )
        strength = str(raw.get("strength") or "hard")
        evidence = str(raw.get("source_evidence") or raw.get("evidence") or "")[:500]
        parameters = raw.get("parameters")
        parameters = deepcopy(parameters) if isinstance(parameters, dict) else {}
        if source not in objects_by_id:
            rejected.append(
                {"update_kind": "relation", "raw": deepcopy(raw), "reason": "unknown source object id"}
            )
            continue
        if relation_type not in GROUNDING_RELATION_TYPES:
            rejected.append(
                {"update_kind": "relation", "raw": deepcopy(raw), "reason": "unsupported relation type"}
            )
            continue
        if strength not in {"hard", "soft"}:
            rejected.append(
                {"update_kind": "relation", "raw": deepcopy(raw), "reason": "strength must be hard or soft"}
            )
            continue
        source_obj = objects_by_id[source]
        previous: dict[str, Any] = {}
        target_obj = objects_by_id.get(target)
        free_space_default = (
            DEFAULT_TUCKED_UNDER_FREE_SPACES.get(
                (
                    str(source_obj.get("category") or ""),
                    str(target_obj.get("category") or ""),
                )
            )
            if target_obj is not None
            else None
        )
        explicit_tucked_under = _explicit_tucked_under_evidence(
            evidence, original_prompt
        )
        if (
            relation_type == "in_front_of"
            and explicit_tucked_under
            and free_space_default
        ):
            requested_type = relation_type
            requested_parameters = deepcopy(parameters)
            relation_type = "tucked_under"
            parameters = {
                "free_space_id": free_space_default,
                "reference_frame": "target_local",
                "preserve_facing": bool(
                    requested_parameters.get("preserve_facing", True)
                ),
            }
            normalizations.append(
                {
                    "kind": "explicit_tucked_under_type_restored",
                    "source": source,
                    "target": target,
                    "requested_type": requested_type,
                    "effective_type": relation_type,
                    "free_space_id": free_space_default,
                    "source_evidence": evidence,
                }
            )
        elif (
            relation_type == "tucked_under"
            and explicit_tucked_under
            and free_space_default
            and not str(parameters.get("free_space_id") or "")
        ):
            parameters["free_space_id"] = free_space_default
            normalizations.append(
                {
                    "kind": "explicit_tucked_under_free_space_inferred",
                    "source": source,
                    "target": target,
                    "effective_type": relation_type,
                    "free_space_id": free_space_default,
                    "source_evidence": evidence,
                }
            )
        if relation_type == "against_wall":
            target = target if target.endswith("_wall") else f"{target}_wall"
            if target not in WALL_NODE_IDS:
                rejected.append(
                    {"update_kind": "relation", "raw": deepcopy(raw), "reason": "against_wall target must be a room wall"}
                )
                continue
            wall = target.removesuffix("_wall")
            previous.update(
                {
                    "preferred_wall": source_obj.get("preferred_wall"),
                    "wall_constraint_strength": source_obj.get("wall_constraint_strength"),
                    "wall_constraint_provenance": source_obj.get("wall_constraint_provenance"),
                }
            )
            source_obj["preferred_wall"] = wall
            source_obj["wall_constraint_strength"] = strength
            source_obj["wall_constraint_provenance"] = "codex_expansion_grounding"
            facing = _wall_facing_constraint(source_obj, wall)
            if facing is not None:
                source_obj["facing_constraint"] = facing
            relations = _remove_conflicting_relations(
                relations, source, relation_type
            )
        elif relation_type == "supported_by":
            if target not in objects_by_id or target == source:
                rejected.append(
                    {"update_kind": "relation", "raw": deepcopy(raw), "reason": "supported_by target must be another object"}
                )
                continue
            if _support_cycle(objects_by_id, source, target):
                rejected.append(
                    {"update_kind": "relation", "raw": deepcopy(raw), "reason": "support relation would create a primary-parent cycle"}
                )
                continue
            previous.update(
                {
                    "support_id": source_obj.get("support_id"),
                    "placement_type": source_obj.get("placement_type"),
                }
            )
            target_category = str(objects_by_id[target].get("category") or "")
            offset = parameters.get("support_offset")
            if not (
                isinstance(offset, list)
                and len(offset) == 2
                and all(isinstance(value, (int, float)) for value in offset)
            ):
                offset = DEFAULT_SUPPORT_OFFSETS.get(
                    (str(source_obj.get("category") or ""), target_category),
                    [0.0, 0.0],
                )
            source_obj.update(
                {
                    "placement_type": "support",
                    "support_id": target,
                    "support_offset": [float(offset[0]), float(offset[1])],
                    "preferred_wall": None,
                }
            )
            source_obj.pop("facing_constraint", None)
            relations = _remove_conflicting_relations(
                relations, source, relation_type
            )
        elif relation_type == "tucked_under":
            if target not in objects_by_id or target == source:
                rejected.append(
                    {
                        "update_kind": "relation",
                        "raw": deepcopy(raw),
                        "reason": "tucked_under target must be another object",
                    }
                )
                continue
            free_space_id = str(parameters.get("free_space_id") or "")
            if not free_space_id:
                rejected.append(
                    {
                        "update_kind": "relation",
                        "raw": deepcopy(raw),
                        "reason": "tucked_under requires parameters.free_space_id",
                    }
                )
                continue
            parameters.update(
                {
                    "free_space_id": free_space_id,
                    "reference_frame": "target_local",
                    "preserve_facing": bool(
                        parameters.get("preserve_facing", True)
                    ),
                }
            )
            strength = "hard"
            relations = _remove_conflicting_relations(
                relations, source, relation_type
            )
        else:
            if target not in objects_by_id or target == source:
                rejected.append(
                    {"update_kind": "relation", "raw": deepcopy(raw), "reason": "relation target must be another object"}
                )
                continue
            if relation_type in {"left_of", "right_of"}:
                locked_role = _locked_side_role(relations, source, target)
                if locked_role is not None:
                    requested_type = relation_type
                    requested_frame = str(
                        parameters.get("reference_frame")
                        or parameters.get("frame")
                        or locked_role["reference_frame"]
                    )
                    if requested_frame not in {"room", "target_local"}:
                        requested_frame = str(locked_role["reference_frame"])
                    explicit_frame = _explicit_reference_frame_evidence(
                        evidence, original_prompt
                    )
                    effective_frame = (
                        requested_frame
                        if explicit_frame
                        else str(locked_role["reference_frame"])
                    )
                    effective_type = str(locked_role["relation_type"])
                    if (
                        requested_type != effective_type
                        or requested_frame != str(locked_role["reference_frame"])
                    ):
                        normalizations.append(
                            {
                                "kind": (
                                    "explicit_reference_frame_override_accepted"
                                    if explicit_frame
                                    else "locked_side_role_override_rejected"
                                ),
                                "source": source,
                                "target": target,
                                "requested_type": requested_type,
                                "effective_type": effective_type,
                                "requested_reference_frame": requested_frame,
                                "effective_reference_frame": effective_frame,
                                "baseline_role_source": locked_role["role_source"],
                                "source_evidence": evidence,
                            }
                        )
                    relation_type = effective_type
                    parameters.update(
                        {
                            "reference_frame": effective_frame,
                            "side_role": locked_role["side_role"],
                            "role_locked": True,
                            "role_reference_frame": effective_frame,
                            "role_source": (
                                "user_explicit_reference_frame"
                                if explicit_frame
                                else locked_role["role_source"]
                            ),
                        }
                    )
                    relations = _remove_relation_edge(
                        relations, source, effective_type, target
                    )
            if relation_type == "faces":
                relations = _remove_conflicting_relations(
                    relations, source, relation_type
                )
            if relation_type == "mirror_symmetric":
                reference_id = str(
                    parameters.get("reference_id")
                    or parameters.get("about")
                    or parameters.get("reference_object")
                    or ""
                )
                if reference_id not in objects_by_id:
                    rejected.append(
                        {
                            "update_kind": "relation",
                            "raw": deepcopy(raw),
                            "reason": "mirror_symmetric requires a known reference_id",
                        }
                    )
                    continue
                parameters["reference_id"] = reference_id
        grounded_relation = {
            "source": source,
            "type": relation_type,
            "target": target,
            "strength": strength,
            "provenance": "codex_expansion_grounding",
            "parameters": {**parameters, "source_evidence": evidence},
        }
        relations.append(grounded_relation)
        accepted.append(
            {
                "update_kind": "relation",
                "relation": deepcopy(grounded_relation),
                "overrode": previous,
            }
        )

    raw_attributes = expanded.get("attribute_updates", [])
    if not isinstance(raw_attributes, list):
        raw_attributes = []
        rejected.append(
            {
                "update_kind": "attribute",
                "reason": "attribute_updates must be a list",
            }
        )
    for raw in raw_attributes[:64]:
        if not isinstance(raw, dict):
            rejected.append(
                {"update_kind": "attribute", "raw": deepcopy(raw), "reason": "not an object"}
            )
            continue
        object_id = str(raw.get("object_id") or "")
        obj = objects_by_id.get(object_id)
        appearance_terms = raw.get("appearance_terms")
        if obj is None or not isinstance(appearance_terms, list):
            rejected.append(
                {"update_kind": "attribute", "raw": deepcopy(raw), "reason": "unknown object id or invalid appearance_terms"}
            )
            continue
        terms = [str(item).strip() for item in appearance_terms if str(item).strip()][:6]
        obj["appearance_terms_grounded"] = terms
        accepted.append(
            {
                "update_kind": "attribute",
                "object_id": object_id,
                "appearance_terms": terms,
                "source_evidence": str(raw.get("source_evidence") or "")[:500],
            }
        )

    raw_components = expanded.get("component_updates", [])
    if not isinstance(raw_components, list):
        raw_components = []
        rejected.append(
            {
                "update_kind": "component",
                "reason": "component_updates must be a list",
            }
        )
    for raw in raw_components[:32]:
        if not isinstance(raw, dict):
            rejected.append(
                {"update_kind": "component", "raw": deepcopy(raw), "reason": "not an object"}
            )
            continue
        parent_id = str(raw.get("parent_id") or "")
        category = str(raw.get("component_category") or raw.get("category") or "")
        parent = objects_by_id.get(parent_id)
        requirement = next(
            (
                item
                for item in parent.get("component_requirements", [])
                if isinstance(item, dict) and str(item.get("category")) == category
            ),
            None,
        ) if parent else None
        if requirement is None:
            rejected.append(
                {"update_kind": "component", "raw": deepcopy(raw), "reason": "component update must reference an existing baseline requirement"}
            )
            continue
        appearance_terms = raw.get("appearance_terms")
        if isinstance(appearance_terms, list):
            requirement["appearance_terms"] = [
                str(item).strip() for item in appearance_terms if str(item).strip()
            ][:6]
        accepted.append(
            {
                "update_kind": "component",
                "parent_id": parent_id,
                "component_category": category,
                "requested_count": int(requirement.get("requested_count", 0)),
                "count_source": "deterministic_explicit_baseline",
                "source_evidence": str(raw.get("source_evidence") or "")[:500],
            }
        )

    brief["relations"] = relations
    scope_report = ground_constraint_scopes(
        brief, expanded.get("constraint_scopes", [])
    )
    accepted.extend(
        {"update_kind": "constraint_scope", "scope": deepcopy(scope)}
        for scope in scope_report["accepted"]
    )
    rejected.extend(
        {"update_kind": "constraint_scope", **deepcopy(item)}
        for item in scope_report["rejected"]
    )
    group_report = ground_instance_groups(
        brief, expanded.get("instance_groups", [])
    )
    accepted.extend(
        {"update_kind": "instance_group", "group": deepcopy(group)}
        for group in group_report["accepted"]
    )
    rejected.extend(
        {"update_kind": "instance_group", **deepcopy(item)}
        for item in group_report["rejected"]
    )
    report = {
        "schema": "codex_trellis_semantic_grounding_v3",
        "mode": "codex_typed_delta",
        "accepted": accepted,
        "rejected": rejected,
        "normalizations": normalizations,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "normalization_count": len(normalizations),
        "constraint_scopes": {
            "accepted_count": scope_report["accepted_count"],
            "rejected_count": scope_report["rejected_count"],
            "report_schema": scope_report["schema"],
        },
        "instance_groups": {
            "group_count": group_report["group_count"],
            "accepted_count": group_report["accepted_count"],
            "rejected_count": group_report["rejected_count"],
            "report_schema": group_report["schema"],
        },
    }
    brief["semantic_grounding"] = report
    return report


def _category_object(category: str, object_id: str, *, required: bool, priority: int) -> dict[str, Any]:
    definition = OBJECT_DEFINITIONS[category]
    width, length, height = definition["dimensions"]
    placement_type = str(definition.get("placement_type", "floor"))
    return {
        "id": object_id,
        "category": category,
        "required": required,
        "priority": priority,
        "placement_type": placement_type,
        "support_id": None,
        "support_offset": [0.0, 0.0],
        "preferred_wall": "north" if placement_type == "wall" else None,
        "mount_height": definition.get("mount_height"),
        "dimensions": {"width": width, "length": length, "height": height},
        "requested_dimensions": {"width": width, "length": length, "height": height},
        "dimension_policy": dimension_policy_for_category(category),
    }


def _apply_budget_overrides(
    budget: dict[str, Any],
    *,
    hard_min_objects: int | None,
    target_max_objects: int | None,
    max_auto_inferred_objects: int | None,
) -> dict[str, Any]:
    result = deepcopy(budget)
    if hard_min_objects is not None:
        result["hard_min"] = int(hard_min_objects)
    if target_max_objects is not None:
        result["target_max"] = int(target_max_objects)
    if max_auto_inferred_objects is not None:
        result["max_auto_inferred_objects"] = int(max_auto_inferred_objects)
    if int(result["hard_min"]) < 1:
        raise ValueError("hard minimum scene objects must be at least 1")
    if int(result["target_max"]) < int(result["hard_min"]):
        raise ValueError("target scene object count cannot be lower than the hard minimum")
    if int(result["max_auto_inferred_objects"]) < 0:
        raise ValueError("max auto-inferred objects cannot be negative")
    if int(result.get("hard_runtime_limit", 40)) < int(result["hard_min"]):
        raise ValueError("hard runtime object limit cannot be lower than the hard minimum")
    return result


def _apply_prompt_support_relationships(objects: list[dict[str, Any]], prompt: str) -> None:
    lowered = prompt.lower()
    by_category: dict[str, list[dict[str, Any]]] = {}
    for obj in objects:
        by_category.setdefault(str(obj["category"]), []).append(obj)
    for obj in objects:
        if obj.get("placement_type") != "support" or obj.get("support_id"):
            continue
        definition = OBJECT_DEFINITIONS[str(obj["category"])]
        support_category = str(definition.get("preferred_support_category") or "")
        support = next(iter(by_category.get(support_category, [])), None)
        if support:
            obj["support_id"] = support["id"]
        else:
            obj["placement_type"] = "floor"
    desk = next(iter(by_category.get("desk", [])), None)
    bed = next(iter(by_category.get("bed", [])), None)
    if desk:
        support_offsets = {"book_stack": -0.38, "mug": 0.38}
        for category in ("book_stack", "mug"):
            if category == "mug" and not any(
                phrase in lowered for phrase in ("cup on the desk", "cup on desk", "mug on the desk")
            ):
                continue
            for index, obj in enumerate(by_category.get(category, [])):
                obj.update(
                    {
                        "placement_type": "support",
                        "support_id": desk["id"],
                        "support_offset": [support_offsets[category] + index * 0.22, 0.0],
                        "preferred_wall": None,
                    }
                )
    if bed:
        for index, obj in enumerate(by_category.get("pillow", [])):
            obj.update(
                {
                    "placement_type": "support",
                    "support_id": bed["id"],
                    "support_offset": [-0.35 + index * 0.7, 0.55],
                    "preferred_wall": None,
                }
            )


def build_baseline_brief(
    prompt: str,
    room_type_override: str | None = None,
    *,
    hard_min_objects: int | None = None,
    target_max_objects: int | None = None,
    max_auto_inferred_objects: int | None = None,
    soft_max_objects: int | None = None,
    max_optional_assets: int | None = None,
) -> dict[str, Any]:
    if target_max_objects is not None and soft_max_objects is not None:
        raise ValueError("use target_max_objects or legacy soft_max_objects, not both")
    if max_auto_inferred_objects is not None and max_optional_assets is not None:
        raise ValueError("use max_auto_inferred_objects or legacy max_optional_assets, not both")
    target_max_objects = target_max_objects if target_max_objects is not None else soft_max_objects
    max_auto_inferred_objects = (
        max_auto_inferred_objects
        if max_auto_inferred_objects is not None
        else max_optional_assets
    )
    room_type = detect_room_type(prompt, room_type_override)
    policy = room_policy(room_type)
    styles = detect_styles(prompt)
    explicit_counts = detect_explicit_category_counts(prompt)
    grouped_component_counts = detect_grouped_component_count_contracts(prompt)
    for grouped_category in grouped_component_counts:
        if grouped_category in explicit_counts:
            explicit_counts[grouped_category] = 1
    explicit = list(explicit_counts)
    objects = deepcopy(policy["objects"])
    lowered_prompt = prompt.lower()
    suppress_policy_optional = any(
        phrase in lowered_prompt
        for phrase in (
            "avoid adding decorative clutter",
            "do not add decorative clutter",
            "no objects beyond the mandatory list",
            "不要添加额外装饰",
        )
    )
    if suppress_policy_optional:
        objects = [
            item
            for item in objects
            if item.get("required", True) or str(item["category"]) in explicit_counts
        ]
    for category, requested_count in explicit_counts.items():
        existing = [item for item in objects if str(item["category"]) == category]
        for item in existing:
            item["required"] = True
        for index in range(len(existing), requested_count):
            suffix = f"_{index + 1}" if requested_count > 1 else ""
            objects.append(
                _category_object(
                    category,
                    f"explicit_{category}{suffix}",
                    required=True,
                    priority=60,
                )
            )
        if category in grouped_component_counts:
            grouped_objects = [
                item for item in objects if str(item["category"]) == category
            ]
            if len(grouped_objects) != 1:
                raise ValueError(
                    f"grouped component contract requires one {category} asset"
                )
            grouped_objects[0]["count_contract"] = deepcopy(
                grouped_component_counts[category]
            )
    _apply_prompt_support_relationships(objects, prompt)
    for obj in objects:
        obj["provenance"] = (
            "user_explicit"
            if obj["category"] in explicit
            else ("room_policy_required" if obj.get("required", True) else "room_policy_optional")
        )
    component_resolution = _absorb_integrated_components(objects, prompt)
    pair_instance_counts = {
        category: int(definition.get("pair_instance_count", 0) or 0)
        for category, definition in OBJECT_DEFINITIONS.items()
        if int(definition.get("pair_instance_count", 0) or 0) > 0
    }
    instance_groups = deterministic_pair_groups(
        prompt, objects, pair_instance_counts
    )
    under_specified = len(explicit) < 3 or len(prompt.strip()) < 60
    object_budget = _apply_budget_overrides(
        policy["object_budget"],
        hard_min_objects=hard_min_objects,
        target_max_objects=target_max_objects,
        max_auto_inferred_objects=max_auto_inferred_objects,
    )
    object_budget["required_object_ids"] = [
        str(obj["id"]) for obj in objects if obj.get("required", True)
    ]
    return {
        "schema": "codex_trellis_scene_brief_v2",
        "original_prompt": prompt,
        "expanded_description": prompt,
        "room_type": room_type,
        "styles": styles,
        "room": deepcopy(policy["room"]),
        "architecture": deepcopy(policy["architecture"]),
        "explicit_categories": explicit,
        "explicit_category_counts": explicit_counts,
        "explicit_component_count_contracts": grouped_component_counts,
        "policy_optional_suppressed": suppress_policy_optional,
        "under_specified": under_specified,
        "objects": objects,
        "asset_inventory": _asset_inventory(objects),
        "component_resolution": component_resolution,
        "instance_groups": instance_groups,
        "instance_group_grounding": {
            "schema": "codex_trellis_instance_group_grounding_v1",
            "mode": "deterministic_baseline",
            "deterministic_group_count": len(instance_groups),
            "accepted": [],
            "rejected": [],
            "accepted_count": 0,
            "rejected_count": 0,
            "group_count": len(instance_groups),
            "exclusive_membership_conflicts": {},
            "hierarchy_mutated": False,
            "coordinates_mutated": False,
        },
        "constraint_scopes": [],
        "constraint_scope_grounding": {
            "schema": "codex_trellis_constraint_scope_grounding_v1",
            "mode": "deterministic_baseline",
            "accepted": [],
            "rejected": [],
            "accepted_count": 0,
            "rejected_count": 0,
            "overlapping_memberships": {},
            "auto_merge_performed": False,
            "hierarchy_mutated": False,
            "coordinates_mutated": False,
        },
        "semantic_grounding": {
            "schema": "codex_trellis_semantic_grounding_v3",
            "mode": "deterministic_baseline",
            "accepted": [],
            "rejected": [],
            "normalizations": [],
            "accepted_count": 0,
            "rejected_count": 0,
            "normalization_count": 0,
        },
        "relations": deepcopy(policy["relations"]),
        "hard_rules": deepcopy(policy["hard_rules"]),
        "soft_rules": deepcopy(policy["soft_rules"]),
        "object_budget": object_budget,
        "camera_requirements": camera_requirements_from_prompt(prompt),
        "render_requirements": render_requirements_from_prompt(prompt),
        "allowed_optional_categories": (
            [] if suppress_policy_optional else deepcopy(policy["allowed_optional_categories"])
        ),
        "expansion": {"mode": "rules", "codex_used": False},
    }


def _expansion_prompt(baseline: dict[str, Any]) -> str:
    budget = baseline["object_budget"]
    available_slots = max(0, int(budget["target_max"]) - len(baseline["objects"]))
    optional_limit = min(int(budget["max_auto_inferred_objects"]), available_slots)
    return f"""
You are the semantic expansion stage for a text-to-3D room pipeline.
Preserve every explicit user requirement. Fill only missing functional details.
Do not choose coordinates and do not invent a different room type.

Original prompt:
{baseline['original_prompt']}

Deterministic baseline:
{json.dumps(baseline, indent=2, ensure_ascii=False)}

Return only JSON with this shape:
{{
  "expanded_description": "concise complete room description",
  "styles": ["style tags"],
  "optional_categories": ["zero or more categories from the allowed list"],
  "layout_preferences": ["semantic preferences, no coordinates"],
  "relation_updates": [
    {{
      "source": "exact baseline object id",
      "type": "supported_by|tucked_under|against_wall|faces|left_of|right_of|in_front_of|separated_from|clearance_from|aligned_with|mirror_symmetric",
      "target": "exact object id or north_wall|south_wall|east_wall|west_wall",
      "strength": "hard for explicit user requirements, otherwise soft",
      "parameters": {{
        "support_offset": [0.0, 0.0],
        "tolerance_degrees": 20.0,
        "reference_frame": "target_local|room",
        "min_gap": 0.2,
        "max_gap": 0.9,
        "lateral_tolerance": 0.35,
        "source_anchor": "center|front_face|back_face|left_face|right_face",
        "target_anchor": "center|front_face|back_face|left_face|right_face",
        "axis": "depth|left_right|x|y",
        "alignment_tolerance": 0.1,
        "reference_id": "central exact object id for mirror_symmetric",
        "free_space_id": "named target-local capability such as under_desk",
        "preserve_facing": true
      }},
      "source_evidence": "short exact requirement fragment"
    }}
  ],
  "attribute_updates": [
    {{
      "object_id": "exact baseline object id",
      "appearance_terms": ["terms applying only to this object; may be empty"],
      "source_evidence": "short exact requirement fragment"
    }}
  ],
  "component_updates": [
    {{
      "parent_id": "exact parent object id",
      "component_category": "existing baseline component category",
      "appearance_terms": ["component-local appearance terms"],
      "source_evidence": "short exact requirement fragment"
    }}
  ],
  "constraint_scopes": [
    {{
      "scope_id": "stable snake_case proposal id",
      "domain": "floor|support_surface|container_volume|wall_surface|functional_clearance",
      "scope_kind": "layout_group|support_group|containment_group|functional_group",
      "root_id": "exact baseline object id included in members",
      "members": [
        {{"object_id": "exact baseline object id", "role": "short snake_case semantic role"}}
      ],
      "relation_refs": [
        {{"source": "exact node id", "type": "existing grounded relation type", "target": "exact node id"}}
      ],
      "source_evidence": "exact fragment from the original prompt supporting this grouping"
    }}
  ],
  "instance_groups": [
    {{
      "group_id": "stable snake_case execution-group id",
      "group_kind": "paired_instances|matched_set",
      "cardinality": 2,
      "members": [
        {{"object_id": "exact baseline object id", "role": "left_member|right_member|member_1"}}
      ],
      "asset_contract": {{
        "match_mode": "same_family|same_asset",
        "fallback": "same_asset_reuse|shared_generation_spec|mirror_primary|reject",
        "require_distinct_roles": true,
        "requires_handedness": false,
        "requires_medial_facing": false,
        "medial_facing_tolerance_degrees": 35.0,
        "mirror_axis": "lateral|x|y"
      }},
      "layout_contract": {{
        "arrangement": "side_by_side|mirrored_pair|row",
        "reference_frame": "room|anchor_local",
        "anchor_id": "optional exact baseline object id",
        "anchor_zone": "front|near|free",
        "anchor_min_gap": 0.05,
        "anchor_target_gap": 0.25,
        "anchor_max_gap": 0.80,
        "heading_rule": "preserve|anchor_front|anchor_back",
        "shared_orientation": true,
        "orientation_tolerance_degrees": 15.0,
        "min_gap": 0.03,
        "target_gap": 0.08,
        "max_gap": 0.20,
        "allow_member_respacing": true,
        "allow_rigid_translation": true
      }},
      "source_evidence": "exact fragment from the original prompt proving one matched set"
    }}
  ]
}}

Allowed optional categories:
{json.dumps(baseline['allowed_optional_categories'], ensure_ascii=False)}

Rules:
- Keep the baseline room type unchanged.
- Preserve the exact architecture layer, including its door, windows, and floor material.
- Do not remove required baseline objects.
- Every explicit instance and every room-policy required object is mandatory, even when their
  combined count exceeds the target count. Never summarize a plural request into one instance.
- Add at most {optional_limit} auto-inferred optional categories; returning none is valid.
- The hard minimum is {budget['hard_min']}; {budget['target_max']} is only an automatic-expansion
  target, not a cap on explicit objects. The runtime safety limit is {budget['hard_runtime_limit']}.
- Prefer functional completeness over decorative clutter.
- Treat the baseline ids as immutable entity identifiers. Never invent ids in typed updates.
- Treat baseline relations carrying parameters.role_locked=true as stable semantic roles. Preserve
  their side_role, relation type, and role_reference_frame. A different reference_frame is valid
  only when source_evidence quotes an explicit user viewpoint such as "from the bed's perspective",
  "camera left", or "room right"; ordinary wording such as "on the left side of the bed" does not
  establish a target-local frame.
- Emit relation_updates for every explicit support, wall-contact, facing, ordering, or clearance
  relation, including updates that override a room-policy default. `supported_by` changes the
  primary support parent; `faces` and `against_wall` are typed constraint edges.
- Preserve explicit "tucked under", "pushed under", or "beneath the desk" wording as a hard
  `tucked_under` relation. For an office chair tucked under a desk, set
  parameters.free_space_id=`under_desk`, reference_frame=`target_local`, and
  preserve_facing=true. Never approximate this wording as `in_front_of`.
- For `in_front_of`, use reference_frame `target_local`. For `left_of` and `right_of`, use
  `target_local` only when the wording is relative to the target object's own orientation;
  otherwise use `room`. `left_of` and `right_of` express ordering only: do not add
  lateral_tolerance unless the wording explicitly requires center-line alignment. Express edge
  or face alignment with a separate `aligned_with` update and semantic anchors. For arrangements
  sharing a wall, align `back_face` to `back_face` on the `depth` axis. Express an explicit
  symmetric pair with one `mirror_symmetric` edge between the pair and put the central object's
  exact id in parameters.reference_id. Add numeric min/max gaps only when implied by usable
  clearance, nearness, or separation, and use metres.
- Do not copy a material or appearance term from one object to another object mentioned in the
  same sentence. Emit an attribute_updates row for each explicitly mentioned object in such a
  sentence, using an empty appearance_terms list when that object has no stated appearance.
- Component updates may only refine component requirements already present in the deterministic
  baseline; preserve its explicit component counts.
- Furniture semantics may be proposed through constraint_scopes. A scope is an advisory computation
  view, not a new hierarchy: it must not change support parents or coordinates. Use only exact
  baseline object ids and relation_refs that also appear in relation_updates or the baseline.
  Multiple scopes may share an object when they describe different functions or spatial domains.
  Never merge scopes yourself. Quote an exact original-prompt fragment as source_evidence; omit a
  scope when the grouping is unsupported or ambiguous.
- Emit instance_groups only for objects that form one physical matched set, such as an explicit
  pair of slippers or a matching chair set. This is an execution contract, not ownership: members
  remain separate instances for segmentation and collision. One object may belong to at most one
  instance_group, even though it may appear in multiple advisory constraint_scopes. Require exact
  prompt evidence, stable baseline ids, exact cardinality, a same-family asset contract, and a
  bounded arrangement contract. Do not group ordinary co-occurring furniture merely because it is
  near another object. When the deterministic baseline already contains the same member set, refine
  that group rather than creating an overlapping group.
- A chiral pair such as slippers, shoes, or gloves must keep left_member/right_member roles,
  requires_handedness=true, requires_medial_facing=true, fallback=mirror_primary, and
  mirror_axis=lateral so reflection is
  perpendicular to the asset canonical front without reversing its functional heading. When it is anchored
  at the functional front of another object, use reference_frame=anchor_local and
  heading_rule=anchor_front. Member left/right means anatomical wearer left/right, never camera-left,
  filename-left, or source-id-left. Never weaken an existing handed-pair contract to same_asset_reuse.
- Do not include markdown or text outside JSON.
""".strip()


def expand_prompt(
    prompt: str,
    output_dir: Path,
    *,
    room_type_override: str | None,
    mode: str,
    model: str,
    hard_min_objects: int | None = None,
    target_max_objects: int | None = None,
    max_auto_inferred_objects: int | None = None,
) -> dict[str, Any]:
    baseline = build_baseline_brief(
        prompt,
        room_type_override,
        hard_min_objects=hard_min_objects,
        target_max_objects=target_max_objects,
        max_auto_inferred_objects=max_auto_inferred_objects,
    )
    use_codex = mode == "codex" or (mode == "hybrid" and baseline["under_specified"])
    if not use_codex:
        baseline["expansion"] = {"mode": mode, "codex_used": False}
        return baseline

    expanded = run_codex_json(
        _expansion_prompt(baseline),
        output_dir,
        stage="text_expansion",
        model=model,
    )
    styles = [str(item) for item in expanded.get("styles", []) if str(item).strip()]
    if styles:
        baseline["styles"] = styles[:6]
    baseline["expanded_description"] = str(
        expanded.get("expanded_description") or baseline["original_prompt"]
    ).strip()
    optional = []
    existing_categories = {str(item["category"]) for item in baseline["objects"]}
    allowed_categories = set(baseline["allowed_optional_categories"])
    budget = baseline["object_budget"]
    optional_limit = min(
        int(budget["max_auto_inferred_objects"]),
        max(0, int(budget["target_max"]) - len(baseline["objects"])),
    )
    for raw in expanded.get("optional_categories", []) if optional_limit else []:
        category = str(raw).strip()
        if category not in OBJECT_DEFINITIONS or category not in allowed_categories or category in existing_categories:
            continue
        obj = _category_object(category, f"optional_{category}", required=False, priority=20)
        obj["provenance"] = "codex_inferred_optional"
        baseline["objects"].append(obj)
        existing_categories.add(category)
        optional.append(category)
        if len(optional) >= optional_limit:
            break
    baseline["layout_preferences"] = [
        str(item) for item in expanded.get("layout_preferences", []) if str(item).strip()
    ][:24]
    apply_expansion_grounding(baseline, expanded)
    baseline["expansion"] = {
        "mode": mode,
        "codex_used": True,
        "optional_categories_added": optional,
    }
    baseline["asset_inventory"] = _asset_inventory(baseline["objects"])
    return baseline
