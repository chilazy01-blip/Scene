from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


MATERIAL_TAGS = {
    "wood",
    "oak",
    "walnut",
    "fabric",
    "leather",
    "metal",
    "glass",
    "ceramic",
    "brass",
    "paper",
    "rubber",
}


_PROFILE_POLICIES: dict[str, dict[str, Any]] = {
    "open_back_footwear": {
        "primary_roles": ["rubber sole", "fabric or leather upper"],
        "primary_materials": ["rubber", "fabric", "leather"],
        "accent_materials": ["metal", "brass"],
        "protected_parts": ["sole", "upper", "foot-contact surface"],
        "fallback_clause": "a rubber sole and a fabric or leather upper",
    },
    "organic_branching": {
        "primary_roles": ["natural foliage and stems", "separate plant pot"],
        "primary_materials": ["ceramic", "wood", "metal", "glass"],
        "accent_materials": ["brass"],
        "material_scope": "pot_only",
        "protected_parts": ["leaves", "stems"],
        "fallback_clause": "natural green foliage and stems; styled materials apply only to the plant pot",
    },
    "compact_layered": {
        "primary_roles": ["paper page blocks", "book covers"],
        "primary_materials": ["paper", "fabric", "leather"],
        "accent_materials": ["metal", "brass"],
        "protected_parts": ["page blocks"],
        "fallback_clause": "paper page blocks with fabric, paper, or leather covers",
    },
    "compact_rounded_soft": {
        "primary_roles": ["soft filling", "fabric shell"],
        "primary_materials": ["fabric", "leather"],
        "accent_materials": [],
        "protected_parts": ["soft body"],
        "fallback_clause": "a soft filled body with a fabric shell",
    },
    "compact_orthogonal": {
        "primary_roles": ["rigid box body", "surface covering", "small hardware"],
        "primary_materials": ["fabric", "wood", "metal", "leather"],
        "accent_materials": ["metal", "brass"],
        "protected_parts": ["lid", "box body"],
        "fallback_clause": "a coherent box body and lid; accent materials remain limited to small hardware",
    },
    "open_repeated_frame": {
        "primary_roles": ["load-bearing frame", "shelves"],
        "primary_materials": ["wood", "oak", "walnut", "metal", "glass"],
        "accent_materials": ["metal", "brass"],
        "protected_parts": ["open storage cavities"],
        "fallback_clause": "one coherent load-bearing frame and repeated shelves",
    },
    "skeletal_support": {
        "primary_roles": ["load-bearing frame", "seat and back contact surfaces"],
        "primary_materials": ["metal", "wood", "fabric", "leather"],
        "accent_materials": ["brass", "metal"],
        "protected_parts": ["seat", "backrest", "support base"],
        "fallback_clause": "a coherent load-bearing frame with plausible seat and back contact materials",
    },
    "slender_radial": {
        "primary_roles": ["structural body", "shade or light head", "integrated base"],
        "primary_materials": ["metal", "wood", "glass", "ceramic", "fabric", "brass"],
        "accent_materials": ["metal", "brass"],
        "protected_parts": ["light head", "stem", "integrated base"],
        "fallback_clause": "plausible materials assigned separately to the shade, stem, and integrated base",
    },
}


def material_policy_for_semantic_form(
    semantic_form_contract: dict[str, Any] | None,
) -> dict[str, Any]:
    semantic_form_contract = (
        semantic_form_contract if isinstance(semantic_form_contract, dict) else {}
    )
    profile = str(semantic_form_contract.get("shape_profile") or "general_object")
    policy = deepcopy(_PROFILE_POLICIES.get(profile, {}))
    policy.setdefault("primary_roles", ["object body"])
    policy.setdefault("primary_materials", sorted(MATERIAL_TAGS))
    policy.setdefault("accent_materials", ["metal", "brass"])
    policy.setdefault("protected_parts", [])
    policy.setdefault(
        "fallback_clause",
        "physically plausible materials assigned to the appropriate object parts",
    )
    policy["shape_profile"] = profile
    policy["policy_basis"] = "semantic_shape_profile_and_part_roles"
    policy["category_specific_branching"] = False
    return policy


def _material_tag(term: str) -> str | None:
    lowered = str(term).strip().lower().replace("_", " ")
    for tag in sorted(MATERIAL_TAGS, key=len, reverse=True):
        if tag in lowered:
            return tag
    return None


def compile_material_applicability(
    semantic_form_contract: dict[str, Any] | None,
    appearance_terms: Iterable[str],
    *,
    style_tags: Iterable[str] = (),
) -> dict[str, Any]:
    """Scope style materials to physically plausible part roles.

    This is deliberately keyed by semantic form/part roles rather than category
    names. It prevents a global material accent from silently becoming the
    substance of every part of an object.
    """

    policy = material_policy_for_semantic_form(semantic_form_contract)
    original = [str(item).strip() for item in appearance_terms if str(item).strip()]
    requested: list[dict[str, str]] = []
    non_material_terms: list[str] = []
    for term in original:
        tag = _material_tag(term)
        if tag is None:
            non_material_terms.append(term)
        else:
            requested.append({"term": term, "tag": tag})
    for raw in style_tags:
        tag = _material_tag(str(raw))
        if tag and not any(item["tag"] == tag for item in requested):
            requested.append({"term": str(raw), "tag": tag})

    profile = str(policy["shape_profile"])
    prompt_terms = list(non_material_terms)
    assignments: list[dict[str, str]] = []
    redirected: list[dict[str, str]] = []
    requested_tags = {item["tag"] for item in requested}

    if profile == "open_back_footwear":
        prompt_terms.append("rubber sole and fabric or leather upper")
        for item in requested:
            if item["tag"] in {"metal", "brass"}:
                prompt_terms.append(f"{item['term']} accents only, never a rigid metal foot-contact body")
                redirected.append({**item, "scope": "small_hardware_or_trim"})
            elif item["tag"] in set(policy["primary_materials"]):
                assignments.append({**item, "scope": "sole_or_upper"})
    elif profile == "organic_branching":
        prompt_terms.append("natural green foliage and stems")
        for item in requested:
            prompt_terms.append(f"{item['term']} plant pot only")
            redirected.append({**item, "scope": "plant_pot_only"})
    elif profile == "compact_layered":
        prompt_terms.append("paper page blocks")
        for item in requested:
            if item["tag"] in {"metal", "brass"}:
                prompt_terms.append(f"{item['term']} cover accents only, not metal page blocks")
                redirected.append({**item, "scope": "cover_accent_only"})
            else:
                assignments.append({**item, "scope": "covers_or_pages"})
    elif profile == "compact_rounded_soft":
        prompt_terms.append("soft filled body with a fabric shell")
        for item in requested:
            if item["tag"] not in set(policy["primary_materials"]):
                redirected.append({**item, "scope": "omitted_from_soft_body"})
            else:
                assignments.append({**item, "scope": "soft_shell"})
    elif profile == "compact_orthogonal":
        for item in requested:
            if item["tag"] in {"metal", "brass"}:
                prompt_terms.append(f"{item['term']} limited to small hardware or trim")
                redirected.append({**item, "scope": "small_hardware_or_trim"})
            else:
                assignments.append({**item, "scope": "box_body_or_covering"})
    elif profile == "skeletal_support":
        for item in requested:
            if item["tag"] in {"metal", "wood", "oak", "walnut", "brass"}:
                scope = "load_bearing_frame"
                prompt_terms.append(f"{item['term']} load bearing frame")
                assignments.append({**item, "scope": scope})
            elif item["tag"] in {"fabric", "leather"}:
                scope = "seat_or_back_surface"
                prompt_terms.append(f"{item['term']} seat or back surface")
                assignments.append({**item, "scope": scope})
            else:
                redirected.append(
                    {**item, "scope": "omitted_from_skeletal_support"}
                )
    elif profile == "slender_radial":
        for item in requested:
            prompt_terms.append(f"{item['term']} assigned to the shade, stem, or integrated base as physically appropriate")
            assignments.append({**item, "scope": "shade_stem_or_base"})
    elif profile == "open_repeated_frame":
        for item in requested:
            prompt_terms.append(f"{item['term']} frame or shelves")
            assignments.append({**item, "scope": "frame_or_shelves"})
    else:
        prompt_terms.extend(item["term"] for item in requested)
        assignments.extend({**item, "scope": "object_body"} for item in requested)

    if not requested_tags and policy.get("fallback_clause"):
        prompt_terms.append(str(policy["fallback_clause"]))
    prompt_terms = list(dict.fromkeys(term for term in prompt_terms if term))
    return {
        "schema": "scene_dna_material_applicability_v1",
        "shape_profile": profile,
        "policy": policy,
        "original_appearance_terms": original,
        "requested_materials": requested,
        "primary_assignments": assignments,
        "redirected_or_scoped_materials": redirected,
        "prompt_appearance_terms": prompt_terms,
        "global_material_cannot_override_part_physics": True,
        "audit_status": "compiled",
    }
