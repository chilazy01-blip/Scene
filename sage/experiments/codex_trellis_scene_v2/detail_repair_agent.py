from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .scene_dna_feasibility import assess_3d_feasibility


STRUCTURE_ISSUES = {
    "structure:basic_foreground": (
        "evidence_or_completeness",
        "object evidence is clipped, empty, or incompletely visible",
    ),
    "structure:fragmentation": (
        "detached_geometry",
        "unexpected detached geometry is present",
    ),
    "structure:compact_silhouette": (
        "silhouette_deformation",
        "the silhouette does not satisfy the requested compact form",
    ),
    "structure:internal_holes": (
        "unintended_hole",
        "a closed form contains an unintended hole",
    ),
    "structure:lower_overhang": (
        "forbidden_ground_geometry",
        "a broad connected support or ground artifact appears below the object",
    ),
    "structure:lower_platform": (
        "forbidden_platform",
        "a display platform or full-width base appears below the object",
    ),
    "opposite_view_inconsistent": (
        "view_inconsistent_geometry",
        "opposite views disagree too strongly about the object's proportions",
    ),
    "excessive_nonuniform_scale": (
        "proportion_distortion",
        "requested dimensions require destructive non-uniform scaling",
    ),
    "four_views_incomplete": (
        "evidence_capture_missing",
        "one or more required diagnostic views are missing",
    ),
    "multiview_not_evaluated": (
        "evidence_capture_missing",
        "the asset has not received a complete diagnostic render",
    ),
}


def _finding(
    issue_type: str,
    description: str,
    *,
    severity: str,
    evidence: dict[str, Any],
    preferred_action: str,
    issue_key: str,
) -> dict[str, Any]:
    return {
        "issue_id": issue_key.replace(":", "_"),
        "issue_type": issue_type,
        "description": description,
        "severity": severity,
        "evidence": deepcopy(evidence),
        "preferred_action": preferred_action,
    }


def diagnose_detail_failures(report: dict[str, Any]) -> dict[str, Any]:
    """Compile auditable findings from multi-view evidence.

    This is deliberately category independent.  A critic may explain a defect,
    but only measured evidence is allowed to trigger an executor action.
    """

    assessment = assess_3d_feasibility(report)
    findings: list[dict[str, Any]] = []
    views = report.get("views") if isinstance(report.get("views"), dict) else {}
    clipped_axes = sorted(
        axis
        for axis, row in views.items()
        if isinstance(row, dict)
        and float(row.get("border_foreground_ratio", 0.0) or 0.0) > 0.02
    )
    if clipped_axes:
        findings.append(
            _finding(
                "evidence_capture_clipping",
                "diagnostic framing clips or touches the object boundary",
                severity="high",
                evidence={"axes": clipped_axes, "threshold": 0.02},
                preferred_action="rerender_same_asset_with_safe_framing",
                issue_key="capture:clipping",
            )
        )
    for key in assessment["hard_failures"]:
        if key == "structure:basic_foreground" and clipped_axes:
            continue
        issue_type, description = STRUCTURE_ISSUES.get(
            key, ("unclassified_hard_failure", key)
        )
        findings.append(
            _finding(
                issue_type,
                description,
                severity="critical",
                evidence={"hard_failure": key},
                preferred_action="switch_reference_and_regenerate_single_asset",
                issue_key=key,
            )
        )
    semantic = report.get("semantic_style_multiview")
    semantic = semantic if isinstance(semantic, dict) else {}
    if semantic.get("evaluated") and not report.get("semantic_category_verified"):
        findings.append(
            _finding(
                "semantic_or_required_part_mismatch",
                "the object identity or required parts are not reliable across all views",
                severity="high",
                evidence={
                    "mean_semantic_score": semantic.get("mean_semantic_score"),
                    "minimum_semantic_score": semantic.get("minimum_semantic_score"),
                },
                preferred_action="switch_reference_and_regenerate_single_asset",
                issue_key="semantic:identity_or_parts",
            )
        )
    if semantic.get("evaluated") and not report.get("semantic_style_verified"):
        findings.append(
            _finding(
                "style_detail_mismatch",
                "style alignment is weak in at least one view",
                severity="medium",
                evidence={
                    "mean_style_alignment_score": semantic.get(
                        "mean_style_alignment_score"
                    ),
                    "minimum_style_alignment_score": semantic.get(
                        "minimum_style_alignment_score"
                    ),
                },
                preferred_action="switch_reference_and_regenerate_single_asset",
                issue_key="style:multiview",
            )
        )
    return {
        "schema": "scene_detail_diagnosis_v1",
        "usable_for_scene_assembly": assessment["usable_for_scene_assembly"],
        "hard_failures": assessment["hard_failures"],
        "finding_count": len(findings),
        "findings": findings,
        "evidence_grounded": True,
    }


def _score_parts(row: dict[str, Any]) -> tuple[float, float, float, float]:
    score = row.get("score") if isinstance(row.get("score"), dict) else {}
    semantic = score.get("semantic") if isinstance(score.get("semantic"), dict) else {}
    form = score.get("form") if isinstance(score.get("form"), dict) else {}
    combined = float(score.get("score", 0.0) or 0.0)
    semantic_score = float(semantic.get("score", combined) or 0.0)
    form_score = float(form.get("score", combined) or 0.0)
    pixel_score = float(score.get("legacy_pixel_score", combined) or 0.0)
    return combined, semantic_score, form_score, pixel_score


def rank_repair_references(
    candidate_batch: dict[str, Any],
    diagnosis: dict[str, Any],
    *,
    excluded_paths: Iterable[str | Path] = (),
) -> list[dict[str, Any]]:
    """Rank unused, gate-passing 2D references for the observed failure type."""

    if not diagnosis.get("findings"):
        return []
    excluded = {str(Path(item).resolve()) for item in excluded_paths if str(item)}
    attempts = {
        int(item.get("attempt", index) or 0): item
        for index, item in enumerate(candidate_batch.get("reference_attempts", []))
        if isinstance(item, dict)
    }
    issue_types = {
        str(item.get("issue_type") or "")
        for item in diagnosis.get("findings", [])
        if isinstance(item, dict)
    }
    form_priority = bool(
        issue_types
        & {
            "forbidden_platform",
            "forbidden_ground_geometry",
            "detached_geometry",
            "silhouette_deformation",
            "unintended_hole",
            "view_inconsistent_geometry",
            "proportion_distortion",
        }
    )
    semantic_priority = "semantic_or_required_part_mismatch" in issue_types
    rows: list[dict[str, Any]] = []
    selection = candidate_batch.get("scene_dna_candidate_selection", {})
    for ranked in selection.get("ranking", []):
        if not isinstance(ranked, dict) or not ranked.get("eligible"):
            continue
        attempt = int(ranked.get("attempt", 0) or 0)
        source = attempts.get(attempt, {})
        path = Path(str(source.get("prepared_image_path") or ""))
        if not path.is_file() or str(path.resolve()) in excluded:
            continue
        combined, semantic_score, form_score, pixel_score = _score_parts(ranked)
        if form_priority:
            repair_score = 0.50 * form_score + 0.25 * semantic_score + 0.25 * combined
            rationale = "form_failure_weighting"
        elif semantic_priority:
            repair_score = 0.50 * semantic_score + 0.30 * form_score + 0.20 * combined
            rationale = "semantic_part_failure_weighting"
        else:
            repair_score = (
                0.35 * combined
                + 0.25 * semantic_score
                + 0.20 * form_score
                + 0.20 * pixel_score
            )
            rationale = "balanced_detail_weighting"
        rows.append(
            {
                "attempt": attempt,
                "reference_job_id": ranked.get("reference_job_id"),
                "reference_image_path": str(path.resolve()),
                "repair_score": round(repair_score, 6),
                "ranking_rationale": rationale,
                "source_scores": {
                    "combined": combined,
                    "semantic": semantic_score,
                    "form": form_score,
                    "pixel": pixel_score,
                },
            }
        )
    return sorted(
        rows,
        key=lambda item: (-float(item["repair_score"]), int(item["attempt"])),
    )


def build_repair_plan(
    case_id: str,
    diagnosis: dict[str, Any],
    ranked_references: list[dict[str, Any]],
    *,
    max_generation_attempts: int,
) -> dict[str, Any]:
    capture_only = any(
        item.get("issue_type") == "evidence_capture_clipping"
        for item in diagnosis.get("findings", [])
        if isinstance(item, dict)
    )
    actions: list[dict[str, Any]] = []
    if capture_only:
        actions.append(
            {
                "action": "rerender_same_asset_with_safe_framing",
                "mutates_asset": False,
                "costs_generation_budget": False,
            }
        )
    if any(
        item.get("issue_type") in {"forbidden_platform", "forbidden_ground_geometry"}
        for item in diagnosis.get("findings", [])
        if isinstance(item, dict)
    ):
        actions.append(
            {
                "action": "localize_and_repair_defect_faces",
                "mutates_asset": True,
                "costs_generation_budget": False,
                "scope": "multiview_mask_to_polygon_ids_then_connected_low_region",
                "minimum_supporting_views": 2,
                "maximum_removed_face_fraction": 0.50,
                "requires_material_preservation": True,
            }
        )
        actions.append(
            {
                "action": "trim_forbidden_lower_platform",
                "mutates_asset": True,
                "costs_generation_budget": False,
                "scope": "measured_low_geometry_outside_upper_subject_footprint",
                "mesh_repair_variants": [
                    {
                        "trim_mode": "remove_low_broad_components",
                        "lower_cutoff_ratio": 0.34,
                        "footprint_expand": 1.45,
                    },
                    {
                        "trim_mode": "remove_low_slab",
                        "lower_cutoff_ratio": 0.22,
                        "footprint_expand": 1.45,
                    },
                    {
                        "trim_mode": "remove_low_slab",
                        "lower_cutoff_ratio": 0.28,
                        "footprint_expand": 1.45,
                    },
                    {
                        "trim_mode": "remove_low_slab",
                        "lower_cutoff_ratio": 0.34,
                        "footprint_expand": 1.45,
                    },
                    {
                        "trim_mode": "outside_upper_footprint",
                        "lower_cutoff_ratio": 0.34,
                        "footprint_expand": 1.20,
                    },
                ],
                "maximum_removed_face_fraction": 0.60,
            }
        )
    for candidate in ranked_references[: max(0, int(max_generation_attempts))]:
        actions.append(
            {
                "action": "switch_reference_and_regenerate_single_asset",
                "mutates_asset": True,
                "costs_generation_budget": True,
                **deepcopy(candidate),
            }
        )
    return {
        "schema": "scene_detail_repair_plan_v1",
        "case_id": case_id,
        "control_is_immutable": True,
        "maximum_generation_attempts": int(max_generation_attempts),
        "whole_scene_regeneration_allowed": False,
        "actions": actions,
        "stop_condition": "first_verified_improvement_or_budget_exhausted",
    }


def verify_repair(
    control_report: dict[str, Any],
    repair_report: dict[str, Any],
    *,
    edit_certificate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept only a causal detail improvement with no hard regression."""

    before = assess_3d_feasibility(control_report)
    after = assess_3d_feasibility(repair_report)
    before_hard = set(before["hard_failures"])
    after_hard = set(after["hard_failures"])
    resolved = sorted(before_hard - after_hard)
    introduced = sorted(after_hard - before_hard)
    control_semantic = control_report.get("semantic_style_multiview", {})
    repair_semantic = repair_report.get("semantic_style_multiview", {})
    control_semantic_score = float(
        control_semantic.get("mean_semantic_score", 0.0) or 0.0
    )
    repair_semantic_score = float(
        repair_semantic.get("mean_semantic_score", 0.0) or 0.0
    )
    control_style = float(
        control_semantic.get("mean_style_alignment_score", 0.0) or 0.0
    )
    repair_style = float(
        repair_semantic.get("mean_style_alignment_score", 0.0) or 0.0
    )
    control_auto = float(control_report.get("automated_score", 0.0) or 0.0)
    repair_auto = float(repair_report.get("automated_score", 0.0) or 0.0)
    semantic_regression = repair_semantic_score < control_semantic_score - 0.05
    style_regression = repair_style < control_style - 0.08
    score_regression = repair_auto < control_auto - 0.08
    soft_improvement = bool(
        (
            not control_report.get("semantic_category_verified")
            and repair_report.get("semantic_category_verified")
        )
        or (
            not control_report.get("semantic_style_verified")
            and repair_report.get("semantic_style_verified")
        )
        or repair_semantic_score >= control_semantic_score + 0.08
    )
    hard_improvement = bool(resolved) or (
        not before["usable_for_scene_assembly"] and after["usable_for_scene_assembly"]
    )
    edit_certificate = edit_certificate if isinstance(edit_certificate, dict) else {}
    material = (
        edit_certificate.get("material_preservation")
        if isinstance(edit_certificate.get("material_preservation"), dict)
        else {}
    )
    scope = (
        edit_certificate.get("scope_certificate")
        if isinstance(edit_certificate.get("scope_certificate"), dict)
        else {}
    )
    localized_material_style_evidence = bool(
        edit_certificate.get("schema") == "scene_detail_localized_mesh_repair_v1"
        and edit_certificate.get("evidence_grounded")
        and edit_certificate.get("multi_view_confirmed")
        and material.get("verified")
        and material.get("surviving_face_material_assignments_preserved")
        and not material.get("texture_and_node_parameters_modified")
        and scope.get("only_seed_connected_faces_below_height_limit_removed")
        and not scope.get("preexisting_open_boundaries_filled")
        and not scope.get("whole_asset_regeneration_used")
        and float(edit_certificate.get("removed_face_fraction", 1.0) or 1.0)
        <= float(edit_certificate.get("maximum_removed_face_fraction", 0.0) or 0.0)
    )
    # The zero-shot style contrast score mixes silhouette and appearance.  A
    # verified local deletion is expected to change the silhouette.  For this
    # narrowly certified operation, unchanged materials/textures are stronger
    # evidence of appearance non-regression than that entangled soft score.
    style_gate_passed = bool(not style_regression or localized_material_style_evidence)
    accepted = bool(
        after["usable_for_scene_assembly"]
        and not introduced
        and not semantic_regression
        and style_gate_passed
        and not score_regression
        and (hard_improvement or soft_improvement)
    )
    return {
        "schema": "scene_detail_repair_verification_v1",
        "accepted": accepted,
        "decision": "commit_repair" if accepted else "rollback_repair",
        "control_unchanged": True,
        "resolved_hard_failures": resolved,
        "introduced_hard_failures": introduced,
        "before_usable": before["usable_for_scene_assembly"],
        "after_usable": after["usable_for_scene_assembly"],
        "semantic_delta": round(repair_semantic_score - control_semantic_score, 6),
        "style_delta": round(repair_style - control_style, 6),
        "automated_score_delta": round(repair_auto - control_auto, 6),
        "regression_gates": {
            "semantic": not semantic_regression,
            "style": style_gate_passed,
            "automated_score": not score_regression,
            "hard_failures": not introduced,
        },
        "style_non_regression_evidence": (
            "localized_material_and_texture_preservation_certificate"
            if style_regression and localized_material_style_evidence
            else "multiview_zero_shot_style_score"
        ),
        "zero_shot_style_score_regressed": bool(style_regression),
        "localized_material_style_evidence_accepted": bool(
            style_regression and localized_material_style_evidence
        ),
    }
