from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .brief import ASSET_SEMANTIC_FORM_HINTS, category_appearance_terms
from .scene_dna_materials import (
    compile_material_applicability,
    material_policy_for_semantic_form,
)


SCENE_DNA_SCHEMA = "codex_trellis_scene_dna_v1"
HARMONY_CERTIFICATE_SCHEMA = "codex_trellis_asset_harmony_certificate_v1"

# Scene-wide palette evidence describes the room as a whole.  Do not copy a
# colour or material onto every generated object unless that same palette term
# is grounded in the object's local requirements.  Structural style words such
# as "modern" or "warm" remain globally applicable.
OBJECT_LOCAL_PALETTE_TAGS = {
    "black",
    "blue",
    "brass",
    "brown",
    "ceramic",
    "fabric",
    "glass",
    "gold",
    "gray",
    "green",
    "grey",
    "leather",
    "metal",
    "oak",
    "orange",
    "paper",
    "pink",
    "red",
    "rubber",
    "silver",
    "tan",
    "walnut",
    "white",
    "wood",
    "yellow",
}


TAG_PATTERNS: dict[str, tuple[str, ...]] = {
    "modern": ("modern", "contemporary", "现代"),
    "minimal": (
        "minimalist",
        "minimal design",
        "minimal style",
        "minimal interior",
        "minimal room",
        "简约",
        "极简",
    ),
    "classic": ("classic", "traditional", "古典", "传统"),
    "industrial": ("industrial", "工业风"),
    "scandinavian": ("scandinavian", "nordic", "北欧"),
    "japandi": ("japandi", "侘寂", "日式北欧"),
    "warm": ("warm", "cozy", "温暖", "温馨", "暖色"),
    "cool": ("cool", "cool tone", "cool-toned", "冷色", "冷调"),
    "white": ("white", "白色", "暖白", "冷白"),
    "black": ("black", "黑色"),
    "beige": ("beige", "cream", "米色", "奶油色"),
    "gray": ("gray", "grey", "灰色", "灰调"),
    "blue": ("blue", "navy", "蓝色", "深蓝"),
    "green": ("green", "sage", "绿色", "鼠尾草"),
    "red": ("red", "红色"),
    "wood": ("wood", "wooden", "原木", "木质", "木制"),
    "oak": ("oak", "橡木"),
    "walnut": ("walnut", "胡桃木"),
    "fabric": ("fabric", "linen", "velvet", "woven", "布艺", "织物", "亚麻", "天鹅绒"),
    "leather": ("leather", "皮革"),
    "metal": ("metal", "metallic", "金属"),
    "glass": ("glass", "玻璃"),
    "ceramic": ("ceramic", "陶瓷"),
    "brass": ("brass", "黄铜"),
    "paper": ("paper", "page block", "纸", "书页"),
    "rubber": ("rubber", "橡胶"),
    "clean_lines": ("clean lines", "clean-lined", "利落线条", "简洁线条"),
    "rounded": ("rounded", "curved", "圆润", "曲线"),
    "ornate": ("ornate", "decorative carving", "雕花", "繁复"),
}

TAG_ALIASES = {
    "traditional": "classic",
    "contemporary": "modern",
    "minimalist": "minimal",
    "cream": "beige",
    "grey": "gray",
    "navy": "blue",
    "wooden": "wood",
    "linen": "fabric",
    "velvet": "fabric",
    "metallic": "metal",
}

TAG_FACETS: dict[str, str] = {
    **{tag: "style_family" for tag in ("modern", "minimal", "classic", "industrial", "scandinavian", "japandi")},
    **{tag: "temperature" for tag in ("warm", "cool")},
    **{tag: "palette" for tag in ("white", "black", "beige", "gray", "blue", "green", "red")},
    **{tag: "material" for tag in ("wood", "oak", "walnut", "fabric", "leather", "metal", "glass", "ceramic", "brass", "paper", "rubber")},
    **{tag: "form_language" for tag in ("clean_lines", "rounded", "ornate")},
}

CONFLICTS = {
    "warm": {"cool"},
    "cool": {"warm"},
    "modern": {"classic"},
    "classic": {"modern", "minimal"},
    "minimal": {"classic", "ornate"},
    "ornate": {"minimal", "clean_lines"},
    "clean_lines": {"ornate"},
}

AESTHETIC_RELATION_COUPLING = {
    "part_of": 1.0,
    "included_by_asset": 1.0,
    "mirror_symmetric": 0.95,
    "contained_in": 0.85,
    "supported_by": 0.75,
    "tucked_under": 0.75,
    "partially_inserted": 0.75,
    "aligned_with": 0.65,
    "faces": 0.55,
    "left_of": 0.45,
    "right_of": 0.45,
}

SOURCE_PRIORITY = {
    "user_prompt": 4,
    "user_reference_image": 3,
    "curated_anchor_consensus": 2,
    "architecture": 2,
    "room_default": 1,
}


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _normalize_tag(value: str) -> str:
    tag = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return TAG_ALIASES.get(tag, tag)


def _tags_from_text(text: str) -> set[str]:
    lowered = str(text).lower()
    return {
        tag
        for tag, patterns in TAG_PATTERNS.items()
        if any(
            (
                bool(
                    re.search(
                        rf"(?<![a-z]){re.escape(pattern.lower())}(?![a-z])",
                        lowered,
                    )
                )
                if re.search(r"[a-z]", pattern.lower())
                else pattern.lower() in lowered
            )
            for pattern in patterns
        )
    }


def _tags_from_asset(asset: dict[str, Any]) -> set[str]:
    tags = {_normalize_tag(item) for item in asset.get("styles", []) if str(item).strip()}
    for key in ("materials", "palette", "form_language"):
        value = asset.get(key)
        if isinstance(value, list):
            tags.update(_normalize_tag(item) for item in value if str(item).strip())
        elif isinstance(value, str) and value.strip():
            tags.add(_normalize_tag(value))
    profile = asset.get("style_profile")
    if isinstance(profile, dict):
        for value in profile.values():
            if isinstance(value, list):
                tags.update(_normalize_tag(item) for item in value if str(item).strip())
            elif isinstance(value, str) and value.strip():
                tags.add(_normalize_tag(value))
    expanded = set(tags)
    for tag in list(tags):
        expanded.update(_tags_from_text(tag.replace("_", " ")))
    return expanded


def _architecture_tags(architecture: dict[str, Any] | None) -> set[str]:
    if not isinstance(architecture, dict):
        return set()
    material_ids: list[str] = []
    floor_material = architecture.get("floor", {}).get("material", {})
    if isinstance(floor_material, dict):
        material_ids.append(str(floor_material.get("material_id") or ""))
    wall_finish = architecture.get("wall_finish", {})
    if isinstance(wall_finish, dict):
        default = wall_finish.get("default", {})
        if isinstance(default, dict):
            material_ids.append(str(default.get("material_id") or ""))
        overrides = wall_finish.get("overrides", {})
        if isinstance(overrides, dict):
            for value in overrides.values():
                if isinstance(value, dict):
                    material_ids.append(str(value.get("material_id") or ""))
    text = " ".join(material_ids).replace("_", " ")
    tags = _tags_from_text(text)
    if "oak" in text or "walnut" in text or "plank" in text:
        tags.add("wood")
    return tags


def _object_ids(brief: dict[str, Any]) -> set[str]:
    return {
        str(obj.get("id"))
        for obj in brief.get("objects", [])
        if isinstance(obj, dict) and obj.get("id")
    }


def _relation_groups(brief: dict[str, Any]) -> list[dict[str, Any]]:
    object_ids = _object_ids(brief)
    graph = brief.get("scene_graph")
    relations = graph.get("relations", []) if isinstance(graph, dict) else brief.get("relations", [])
    parent: dict[str, str] = {object_id: object_id for object_id in object_ids}
    evidence: list[dict[str, Any]] = []

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for relation in relations if isinstance(relations, list) else []:
        if not isinstance(relation, dict):
            continue
        source = str(relation.get("source") or "")
        target = str(relation.get("target") or "")
        relation_type = str(relation.get("type") or relation.get("relation_type") or "")
        coupling = float(AESTHETIC_RELATION_COUPLING.get(relation_type, 0.0))
        if source not in object_ids or target not in object_ids or coupling < 0.5:
            continue
        union(source, target)
        evidence.append(
            {
                "source": source,
                "target": target,
                "type": relation_type,
                "coupling": coupling,
            }
        )

    components: dict[str, set[str]] = {}
    for object_id in sorted(object_ids):
        components.setdefault(find(object_id), set()).add(object_id)
    groups: list[dict[str, Any]] = []
    for members in sorted(components.values(), key=lambda value: sorted(value)):
        if len(members) < 2:
            continue
        group_evidence = [
            item for item in evidence if item["source"] in members and item["target"] in members
        ]
        member_list = sorted(members)
        groups.append(
            {
                "group_id": "aesthetic_group_" + _payload_hash(member_list)[:10],
                "members": member_list,
                "relation_evidence": group_evidence,
                "coupling_strength": round(
                    max((float(item["coupling"]) for item in group_evidence), default=0.6), 3
                ),
                "inherit_global_profile": True,
                "allow_object_individuality": True,
            }
        )
    return groups


def build_scene_dna_contract(
    brief: dict[str, Any],
    architecture: dict[str, Any] | None = None,
    curated_anchors: Iterable[dict[str, Any]] | None = None,
    *,
    ablation_mode: str = "relation_aware",
) -> dict[str, Any]:
    """Build one auditable soft style contract without weakening hard geometry gates."""

    supported_modes = {
        "legacy_coarse_tags",
        "user_prompt_only",
        "global_anchor_only",
        "relation_aware",
    }
    if ablation_mode not in supported_modes:
        raise ValueError(
            f"Unsupported SceneDNA ablation mode {ablation_mode!r}; "
            f"expected one of {sorted(supported_modes)}"
        )
    prompt = str(brief.get("original_prompt") or "")
    explicit_tags = (
        _tags_from_text(prompt)
        if ablation_mode in {"user_prompt_only", "relation_aware"}
        else set()
    )
    architecture_profile = (
        _architecture_tags(architecture)
        if ablation_mode == "relation_aware"
        else set()
    )
    anchor_rows = (
        [deepcopy(item) for item in (curated_anchors or []) if isinstance(item, dict)]
        if ablation_mode in {"global_anchor_only", "relation_aware"}
        else []
    )
    anchor_counts: Counter[str] = Counter()
    for row in anchor_rows:
        asset = row.get("asset") if isinstance(row.get("asset"), dict) else row
        anchor_counts.update(_tags_from_asset(asset))
    consensus_minimum = max(1, int(math.ceil(len(anchor_rows) * 0.5)))
    consensus_tags = {
        tag for tag, count in anchor_counts.items() if count >= consensus_minimum
    } if anchor_rows else set()
    brief_styles = (
        {_normalize_tag(item) for item in brief.get("styles", []) if str(item).strip()}
        if ablation_mode == "relation_aware"
        else set()
    )

    entries: dict[str, dict[str, Any]] = {}

    def offer(tag: str, source: str, weight: float, evidence_text: str) -> None:
        normalized = _normalize_tag(tag)
        if not normalized:
            return
        current = entries.get(normalized)
        candidate = {
            "tag": normalized,
            "facet": TAG_FACETS.get(normalized, "descriptor"),
            "weight": round(float(weight), 3),
            "source": source,
            "source_priority": SOURCE_PRIORITY[source],
            "evidence": evidence_text,
        }
        if current is None or (candidate["source_priority"], candidate["weight"]) > (
            current["source_priority"], current["weight"]
        ):
            entries[normalized] = candidate

    for tag in sorted(explicit_tags):
        offer(tag, "user_prompt", 1.0, "explicit term in original prompt")
    for tag in sorted(brief_styles):
        if tag in explicit_tags:
            continue
        if tag == "minimal":
            continue
        offer(tag, "room_default", 0.35, "SceneBrief style default or inferred tag")
    for tag in sorted(architecture_profile):
        offer(tag, "architecture", 0.7, "selected floor or wall material")
    for tag in sorted(consensus_tags):
        offer(
            tag,
            "curated_anchor_consensus",
            0.6,
            f"present in {anchor_counts[tag]}/{len(anchor_rows)} compatible approved anchors",
        )

    # A lower-priority source cannot inject the opposite of an explicit request.
    for explicit in explicit_tags:
        for conflicting in CONFLICTS.get(explicit, set()):
            current = entries.get(conflicting)
            if current and current["source_priority"] < SOURCE_PRIORITY["user_prompt"]:
                entries.pop(conflicting, None)

    desired = sorted(
        entries.values(),
        key=lambda item: (-int(item["source_priority"]), -float(item["weight"]), str(item["tag"])),
    )
    object_profiles: dict[str, dict[str, Any]] = {}
    for obj in brief.get("objects", []):
        if not isinstance(obj, dict) or not obj.get("id"):
            continue
        explicit_local_terms = (
            obj.get("appearance_terms_grounded")
            if isinstance(obj.get("appearance_terms_grounded"), list)
            else obj.get("appearance_terms")
        )
        local_terms = [
            str(item) for item in (explicit_local_terms or []) if str(item).strip()
        ] if ablation_mode in {"user_prompt_only", "relation_aware"} else []
        if (
            not local_terms
            and ablation_mode in {"user_prompt_only", "relation_aware"}
            and obj.get("category")
        ):
            local_terms = category_appearance_terms(
                str(obj.get("category")), prompt
            )
        local_tags = set()
        for term in local_terms:
            local_tags.update(_tags_from_text(term))
            local_tags.add(_normalize_tag(term))
        semantic_form = deepcopy(
            ASSET_SEMANTIC_FORM_HINTS.get(str(obj.get("category") or ""), {})
        )
        semantic_form.setdefault(
            "identity", str(obj.get("category") or "object").replace("_", " ")
        )
        semantic_form.setdefault("shape_profile", "general_object")
        semantic_form.setdefault("required_parts", [])
        semantic_form.setdefault("forbidden_parts", ["display pedestal", "extra prop"])
        semantic_form.setdefault("hard_negative_identities", [])
        semantic_form["schema"] = "scene_dna_semantic_form_contract_v1"
        semantic_form["target_dimensions_m"] = deepcopy(
            obj.get("requested_dimensions") or obj.get("dimensions")
        )
        semantic_form["source"] = (
            "asset_semantic_form_registry_and_requested_dimensions"
        )
        object_profiles[str(obj["id"])] = {
            "category": str(obj.get("category") or ""),
            "individuality_tags": sorted(local_tags),
            "individuality_source": (
                "grounded_object_requirement"
                if explicit_local_terms and local_tags
                else (
                    "category_local_prompt_term" if local_tags else "none"
                )
            ),
            "inherits_global_profile": True,
            "semantic_form_contract": semantic_form,
            "material_applicability_policy": material_policy_for_semantic_form(
                semantic_form
            ),
        }

    anchor_evidence = [
        {
            "object_id": str(row.get("object_id") or ""),
            "category": str(row.get("category") or row.get("asset", {}).get("category") or ""),
            "asset_id": str(row.get("asset", {}).get("asset_id") or row.get("asset_id") or ""),
            "styles": sorted(
                _tags_from_asset(row.get("asset") if isinstance(row.get("asset"), dict) else row)
            ),
        }
        for row in anchor_rows
    ]
    contract: dict[str, Any] = {
        "schema": SCENE_DNA_SCHEMA,
        "contract_version": 1,
        "ablation_mode": ablation_mode,
        "source_priority": [
            "user_prompt",
            "user_reference_image",
            "curated_anchor_consensus",
            "room_default",
        ],
        "reference_image": {
            "provided": False,
            "status": "not_provided",
            "policy": "may_refine_soft_style_only; cannot change category, dimensions, capabilities, or relations",
        },
        "global_profile": {
            "desired_tags": desired,
            "descriptors": [item["tag"] for item in desired],
        },
        "local_aesthetic_groups": (
            _relation_groups(brief) if ablation_mode == "relation_aware" else []
        ),
        "object_profiles": object_profiles,
        "curated_anchor_evidence": anchor_evidence,
        "selection_policy": {
            "hard_gates_before_style": [
                "category",
                "qa_approval",
                "physical_dimensions",
                "capabilities",
                "canonical_front",
                "handedness",
                "support_containment_collision_and_clearance",
            ],
            "style_is_soft_reranking_only": True,
            "style_reranking_enabled": ablation_mode != "legacy_coarse_tags",
            "minimum_harmony_score": 0.55,
            "allow_curated_asset_reselection": True,
            "semantic_form_selection": {
                "status": "experimental_opt_in",
                "semantic_model_family": "siglip2",
                "form_features": "single_view_alpha_morphology_v1",
                "anchor_model_family": "dinov3",
                "semantic_category_margin_gate": 0.42,
                "semantic_minimum_required_part_margin_gate": 0.04,
                "uncertainty_top1_top2_margin": 0.03,
                "default_pipeline_replacement_forbidden_until_blind_test_pass": True,
            },
        },
        "generation_policy": {
            "isolated_2d_candidates": 4,
            "max_candidates_promoted_to_trellis2": 2,
            "max_harmonization_loops": 2,
            "post_generation_multiview_required": True,
            "unverified_generated_assets_must_not_claim_pass": True,
        },
        "failure_policy": {
            "hard_constraint_failure": "reject",
            "style_failure_before_loop_limit": "reselect_or_regenerate",
            "style_failure_after_loop_limit": "keep_best_and_mark_style_review_required",
        },
    }
    contract["contract_hash"] = _payload_hash(contract)
    return contract


def style_context_for_object(contract: dict[str, Any] | None, object_id: str) -> dict[str, Any]:
    if not isinstance(contract, dict):
        return {}
    desired = contract.get("global_profile", {}).get("desired_tags", [])
    global_tags = [
        str(item.get("tag"))
        for item in desired
        if isinstance(item, dict) and item.get("tag")
    ][:8]
    groups = [
        {
            "group_id": str(group.get("group_id") or ""),
            "members": deepcopy(group.get("members", [])),
            "coupling_strength": float(group.get("coupling_strength", 0.0)),
        }
        for group in contract.get("local_aesthetic_groups", [])
        if isinstance(group, dict) and object_id in group.get("members", [])
    ]
    profile = contract.get("object_profiles", {}).get(object_id, {})
    return {
        "contract_hash": contract.get("contract_hash"),
        "global_tags": global_tags,
        "local_groups": groups,
        "individuality_tags": deepcopy(profile.get("individuality_tags", [])),
        "semantic_form_contract": deepcopy(
            profile.get("semantic_form_contract", {})
        ),
        "material_applicability_policy": deepcopy(
            profile.get("material_applicability_policy", {})
        ),
        "minimum_harmony_score": float(
            contract.get("selection_policy", {}).get("minimum_harmony_score", 0.55)
        ),
    }


def score_asset_candidate(
    asset: dict[str, Any],
    contract: dict[str, Any] | None,
    *,
    object_id: str = "",
) -> dict[str, Any]:
    if isinstance(contract, dict) and not bool(
        contract.get("selection_policy", {}).get("style_reranking_enabled", True)
    ):
        contract = None
    context = style_context_for_object(contract, object_id)
    if not context:
        return {
            "enabled": False,
            "score": 0.5,
            "matched_tags": [],
            "missing_tags": [],
            "conflicting_tags": [],
            "candidate_tags": sorted(_tags_from_asset(asset)),
        }
    desired_entries = contract.get("global_profile", {}).get("desired_tags", [])
    weights = {
        str(item["tag"]): float(item.get("weight", 0.5))
        for item in desired_entries
        if isinstance(item, dict) and item.get("tag")
    }
    for tag in context.get("individuality_tags", []):
        weights[str(tag)] = max(1.15, weights.get(str(tag), 0.0))
    candidate_tags = _tags_from_asset(asset)
    matched = sorted(tag for tag in weights if tag in candidate_tags)
    missing = sorted(tag for tag in weights if tag not in candidate_tags)
    conflicts = sorted(
        candidate_tag
        for desired_tag in weights
        for candidate_tag in CONFLICTS.get(desired_tag, set())
        if candidate_tag in candidate_tags
    )
    desired_by_facet: dict[str, set[str]] = {}
    candidate_by_facet: dict[str, set[str]] = {}
    for tag in weights:
        desired_by_facet.setdefault(TAG_FACETS.get(tag, "descriptor"), set()).add(tag)
    for tag in candidate_tags:
        candidate_by_facet.setdefault(TAG_FACETS.get(tag, "descriptor"), set()).add(tag)
    facet_importance = {
        "style_family": 0.30,
        "temperature": 0.18,
        "palette": 0.12,
        "material": 0.15,
        "form_language": 0.15,
        "descriptor": 0.10,
    }
    facet_results: dict[str, dict[str, Any]] = {}
    coverage_numerator = 0.0
    coverage_denominator = 0.0
    for facet, desired_tags in desired_by_facet.items():
        importance = float(facet_importance.get(facet, 0.1))
        candidate_facet_tags = candidate_by_facet.get(facet, set())
        facet_matches = desired_tags & candidate_facet_tags
        if facet_matches:
            facet_score = 1.0
            reason = "matched"
        elif not candidate_facet_tags:
            facet_score = 0.4
            reason = "candidate_metadata_unknown"
        elif facet in {"palette", "material"}:
            facet_score = 0.25
            reason = "allowed_object_contrast"
        else:
            facet_score = 0.0
            reason = "mismatch"
        facet_results[facet] = {
            "score": facet_score,
            "reason": reason,
            "desired_tags": sorted(desired_tags),
            "candidate_tags": sorted(candidate_facet_tags),
        }
        coverage_numerator += importance * facet_score
        coverage_denominator += importance
    coverage = (
        coverage_numerator / coverage_denominator
        if coverage_denominator
        else 0.5
    )
    conflict_penalty = min(0.45, 0.2 * len(set(conflicts)))
    metadata_coverage = min(1.0, len(candidate_tags) / 4.0)
    score = max(0.0, min(1.0, 0.25 + 0.65 * coverage + 0.10 * metadata_coverage - conflict_penalty))
    threshold = float(context.get("minimum_harmony_score", 0.55))
    return {
        "enabled": True,
        "score": round(score, 6),
        "threshold": threshold,
        "passes_soft_threshold": score >= threshold,
        "coverage": round(coverage, 6),
        "facet_results": facet_results,
        "matched_tags": matched,
        "missing_tags": missing,
        "conflicting_tags": sorted(set(conflicts)),
        "candidate_tags": sorted(candidate_tags),
        "object_context": context,
        "metadata_only": True,
        "visual_embedding_evaluated": False,
    }


def apply_scene_dna_to_generation_spec(
    spec: dict[str, Any], contract: dict[str, Any] | None, object_id: str
) -> dict[str, Any]:
    enriched = deepcopy(spec)
    if isinstance(contract, dict) and not bool(
        contract.get("selection_policy", {}).get("style_reranking_enabled", True)
    ):
        return enriched
    context = style_context_for_object(contract, object_id)
    if not context:
        return enriched
    merged_tags = list(
        dict.fromkeys(
            [*context.get("global_tags", []), *enriched.get("style_tags", [])]
        )
    )
    local_palette_evidence = " ".join(
        str(item).lower().replace("_", " ")
        for item in [
            *context.get("individuality_tags", []),
            *enriched.get("appearance_terms", []),
        ]
    )
    filtered_palette_tags: list[str] = []
    applicable_tags: list[str] = []
    for raw_tag in merged_tags:
        tag = str(raw_tag)
        normalized = tag.lower().replace("_", " ")
        if (
            normalized in OBJECT_LOCAL_PALETTE_TAGS
            and normalized not in local_palette_evidence
        ):
            filtered_palette_tags.append(tag)
            continue
        applicable_tags.append(tag)
    enriched["style_tags"] = applicable_tags[:8]
    material_applicability = compile_material_applicability(
        enriched.get("semantic_form_contract")
        or context.get("semantic_form_contract", {}),
        enriched.get("appearance_terms", []),
        style_tags=enriched.get("style_tags", []),
    )
    enriched["appearance_terms_original"] = deepcopy(
        enriched.get("appearance_terms", [])
    )
    enriched["appearance_terms"] = deepcopy(
        material_applicability["prompt_appearance_terms"]
    )
    enriched["scene_dna"] = {
        **context,
        "semantic_form_contract": deepcopy(
            enriched.get("semantic_form_contract")
            or context.get("semantic_form_contract", {})
        ),
        "candidate_funnel": deepcopy(contract.get("generation_policy", {})),
        "hard_constraints_remain_authoritative": True,
        "post_generation_status": "multiview_evaluation_required",
        "material_applicability": material_applicability,
        "filtered_nonlocal_palette_tags": filtered_palette_tags,
    }
    return enriched


def _sha256_file(path: Path, cache: dict[str, str]) -> str | None:
    try:
        resolved = str(path.resolve())
        if resolved in cache:
            return cache[resolved]
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        cache[resolved] = digest.hexdigest()
        return cache[resolved]
    except OSError:
        return None


def build_harmony_certificate(
    contract: dict[str, Any],
    resolution_results: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    threshold = float(contract.get("selection_policy", {}).get("minimum_harmony_score", 0.55))
    file_hash_cache: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    for item in resolution_results:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "unknown")
        scene_dna_score = deepcopy(item.get("scene_dna_score"))
        source_path = item.get("source") or item.get("staged")
        source_hash = _sha256_file(Path(str(source_path)), file_hash_cache) if source_path else None
        candidate_selection = deepcopy(
            item.get("scene_dna_2d_candidate_selection")
        )
        candidate_contract_match = (
            str(candidate_selection.get("contract_hash") or "")
            == str(contract.get("contract_hash") or "")
            if isinstance(candidate_selection, dict)
            else None
        )
        multiview = deepcopy(item.get("scene_dna_multiview"))
        multiview_evaluated = bool(
            isinstance(multiview, dict) and multiview.get("evaluated")
        )
        multiview_contract_match = (
            str(multiview.get("scene_dna_contract_hash") or "")
            == str(contract.get("contract_hash") or "")
            if isinstance(multiview, dict)
            else None
        )
        multiview_automated_pass = bool(
            multiview_evaluated
            and multiview_contract_match is not False
            and multiview.get("automated_pixel_multiview_pass")
        )
        if status == "reused" and isinstance(scene_dna_score, dict):
            harmony_score = float(scene_dna_score.get("score", 0.0))
            acceptance = "pass" if harmony_score >= threshold else "style_review_required"
        elif status == "generated":
            harmony_score = (
                float(multiview.get("automated_score", 0.0))
                if multiview_evaluated
                else None
            )
            if candidate_contract_match is False:
                acceptance = "scene_dna_candidate_contract_mismatch"
            elif multiview_contract_match is False:
                acceptance = "scene_dna_multiview_contract_mismatch"
            elif multiview_automated_pass:
                acceptance = "automated_multiview_pass_semantic_review_required"
            elif multiview_evaluated:
                acceptance = "multiview_failed_style_review_required"
            else:
                acceptance = "multiview_evaluation_required"
        else:
            harmony_score = None
            acceptance = "generation_planned"
        prompt = item.get("bridge_input_prompt")
        records.append(
            {
                "object_id": str(item.get("object_id") or ""),
                "category": str(item.get("category") or ""),
                "asset_id": str(item.get("asset_id") or ""),
                "resolution_status": status,
                "hard_dimension_gate_passed": bool(
                    item.get("dimension_resolution", {}).get("accepted", False)
                ),
                "metadata_harmony": scene_dna_score,
                "pre_trellis_2d_candidate_selection": candidate_selection,
                "pre_trellis_2d_evaluated": isinstance(
                    candidate_selection, dict
                ),
                "pre_trellis_2d_contract_hash_matches": candidate_contract_match,
                "post_generation_multiview": {
                    "required": status in {"generated", "planned_missing"},
                    "evaluated": multiview_evaluated,
                    "contract_hash_matches": multiview_contract_match,
                    "automated_pixel_pass": multiview_automated_pass,
                    "report": multiview,
                },
                "harmony_score": harmony_score,
                "acceptance": acceptance,
                "source_sha256": source_hash,
                "prompt_sha256": hashlib.sha256(str(prompt).encode("utf-8")).hexdigest() if prompt else None,
            }
        )
    review_required = any(item["acceptance"] != "pass" for item in records)
    generated_records = [
        item for item in records if item["resolution_status"] == "generated"
    ]
    all_generated_multiview_pass = bool(generated_records) and all(
        bool(item["post_generation_multiview"].get("automated_pixel_pass"))
        for item in generated_records
    )
    any_generated_multiview_evaluated = any(
        bool(item["post_generation_multiview"].get("evaluated"))
        for item in generated_records
    )
    certificate: dict[str, Any] = {
        "schema": HARMONY_CERTIFICATE_SCHEMA,
        "scene_dna_contract_hash": contract.get("contract_hash"),
        "style_review_required": review_required,
        "all_metadata_harmony_checks_pass": all(
            item["acceptance"] == "pass" for item in records
        ) if records else False,
        "all_hard_dimension_gates_passed": all(
            item["hard_dimension_gate_passed"] for item in records
        ) if records else True,
        "claims_visual_harmony_pass": False,
        "visual_harmony_status": (
            "automated_pixel_multiview_pass_semantic_review_required"
            if all_generated_multiview_pass
            else (
                "automated_multiview_failed"
                if any_generated_multiview_evaluated
                else "not_evaluated"
            )
        ),
        "all_generated_automated_multiview_checks_pass": all_generated_multiview_pass,
        "records": records,
        "limitations": [
            "metadata harmony is not a substitute for rendered multi-view evaluation",
            "generated assets remain unverified until multi-view style and geometry QA is attached",
            "automated multi-view pixel checks do not prove semantic category or design-style correctness",
        ],
    }
    certificate["certificate_hash"] = _payload_hash(certificate)
    return certificate
