from __future__ import annotations

import math
from copy import deepcopy
from typing import Any, Iterable


def assess_3d_feasibility(report: dict[str, Any] | None) -> dict[str, Any]:
    """Turn a multi-view report into a category-independent 3D usability gate."""

    report = report if isinstance(report, dict) else {}
    evaluated = bool(report.get("evaluated"))
    legacy_summary_only = "structure_gate" not in report
    rendered = int(
        report.get("rendered_view_count", 4 if evaluated and legacy_summary_only else 0)
        or 0
    )
    missing = list(report.get("missing_views", []))
    structure = report.get("structure_gate")
    structure = structure if isinstance(structure, dict) else {}
    summary_structure = bool(report.get("structure_gate_passed"))
    structure_checks = {
        "basic_foreground": bool(structure.get("basic_foreground_passed", summary_structure)),
        "fragmentation": bool(structure.get("general_fragment_passed", summary_structure)),
        "compact_silhouette": bool(
            structure.get("compact_silhouette_passed", True)
        ),
        "internal_holes": bool(structure.get("internal_hole_passed", True)),
        "lower_overhang": bool(structure.get("lower_overhang_passed", True)),
        "lower_platform": bool(structure.get("lower_platform_passed", True)),
    }
    structure_fraction = sum(structure_checks.values()) / float(
        len(structure_checks)
    )
    consistency = report.get("opposite_view_consistency")
    consistency = consistency if isinstance(consistency, dict) else {}
    consistency_score = float(consistency.get("minimum_pair_score", 0.0) or 0.0)
    consistency_pass = bool(consistency.get("passes", summary_structure))
    if legacy_summary_only and consistency_pass:
        consistency_score = 1.0
    scale = report.get("scale_anisotropy_gate")
    scale = scale if isinstance(scale, dict) else {}
    scale_pass = bool(scale.get("passes", summary_structure))
    anisotropy = float(
        scale.get("actual", 1.0 if legacy_summary_only and scale_pass else float("inf"))
        or float("inf")
    )
    scale_score = 0.0 if not math.isfinite(anisotropy) else min(1.0, 4.0 / max(4.0, anisotropy))
    view_completeness = min(1.0, rendered / 4.0) if evaluated else 0.0
    hard_geometry = bool(
        report.get("hard_geometry_gate_passed", summary_structure)
    )
    hard_failures: list[str] = []
    if not evaluated:
        hard_failures.append("multiview_not_evaluated")
    if rendered != 4 or missing:
        hard_failures.append("four_views_incomplete")
    hard_failures.extend(
        f"structure:{name}" for name, passed in structure_checks.items() if not passed
    )
    if not consistency_pass:
        hard_failures.append("opposite_view_inconsistent")
    if not scale_pass:
        hard_failures.append("excessive_nonuniform_scale")
    feasibility_score = (
        0.20 * view_completeness
        + 0.45 * structure_fraction
        + 0.20 * max(0.0, min(1.0, consistency_score))
        + 0.15 * scale_score
    )
    usable = bool(
        evaluated
        and rendered == 4
        and not missing
        and hard_geometry
        and not hard_failures
    )
    return {
        "schema": "scene_dna_3d_feasibility_assessment_v1",
        "evaluated": evaluated,
        "usable_for_scene_assembly": usable,
        "hard_geometry_gate_passed": hard_geometry,
        "hard_failures": hard_failures,
        "view_completeness": round(view_completeness, 6),
        "structure_checks": structure_checks,
        "structure_check_fraction": round(structure_fraction, 6),
        "opposite_view_consistency_score": round(consistency_score, 6),
        "scale_score": round(scale_score, 6),
        "feasibility_score": round(feasibility_score, 6),
        "category_specific_branching": False,
    }


def select_3d_candidate(
    candidates: Iterable[dict[str, Any]],
    *,
    require_hard_geometry: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rank generated Top-K candidates while refusing a best-of-failures asset."""

    rows: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        assessment = assess_3d_feasibility(candidate.get("multiview"))
        pixel_pass = bool(
            (candidate.get("multiview") or {}).get(
                "automated_pixel_multiview_pass"
            )
        )
        source_rows.append(candidate)
        rows.append(
            {
                "source_index": len(source_rows) - 1,
                "attempt": int(candidate.get("attempt", 0) or 0),
                "candidate_rank": int(candidate.get("candidate_rank", 1) or 1),
                "path": str(candidate.get("path") or ""),
                "assessment": assessment,
                "automated_pixel_multiview_pass": pixel_pass,
                "full_multiview_acceptance": bool(
                    pixel_pass and assessment["usable_for_scene_assembly"]
                ),
                "automated_score": float(
                    (candidate.get("multiview") or {}).get("automated_score", 0.0)
                    or 0.0
                ),
                "input_index": index,
            }
        )
    if not rows:
        raise ValueError("3D feasibility selection requires at least one candidate")
    ranked = sorted(
        rows,
        key=lambda row: (
            bool(row["full_multiview_acceptance"]),
            bool(row["assessment"]["usable_for_scene_assembly"]),
            float(row["assessment"]["feasibility_score"]),
            float(row["automated_score"]),
            -int(row["attempt"]),
            -int(row["candidate_rank"]),
            -int(row["input_index"]),
        ),
        reverse=True,
    )
    best = ranked[0]
    usable = bool(best["assessment"]["usable_for_scene_assembly"])
    if not require_hard_geometry and not best["assessment"]["evaluated"]:
        usable = True
    decision = {
        "schema": "scene_dna_3d_candidate_selection_v1",
        "candidate_count": len(ranked),
        "require_hard_geometry": bool(require_hard_geometry),
        "selected_source_index": int(best["source_index"]),
        "selected_attempt": int(best["attempt"]),
        "selected_candidate_rank": int(best["candidate_rank"]),
        "selected_path": best["path"],
        "usable_for_scene_assembly": usable,
        "action": (
            "accept_selected_candidate"
            if usable
            else "reject_batch_and_regenerate_without_assembling_best_failure"
        ),
        "ranking": [
            {"selection_rank": index, **deepcopy(row)}
            for index, row in enumerate(ranked, start=1)
        ],
        "selection_order": [
            "full_multiview_acceptance",
            "hard_3d_feasibility",
            "continuous_feasibility_score",
            "soft_style_score",
            "stable_attempt_and_candidate_rank",
        ],
        "best_of_failures_must_not_enter_scene": bool(
            require_hard_geometry and not usable
        ),
    }
    return source_rows[int(best["source_index"])], decision
