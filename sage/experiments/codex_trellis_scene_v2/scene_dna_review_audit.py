from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .scene_dna_blind_review import AXES, CHOICES, _bootstrap_interval, analyze_responses


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {line_number} is not an object")
        rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 3:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_ss = sum((x - left_mean) ** 2 for x in left)
    right_ss = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_ss * right_ss)
    return round(numerator / denominator, 6) if denominator > 1e-12 else None


def _preference_value(outcome: str) -> float | None:
    if outcome == "proposed":
        return 1.0
    if outcome == "baseline":
        return 0.0
    if outcome == "tie":
        return 0.5
    return None


def _experiment_context(comparisons_doc: dict[str, Any]) -> dict[str, Any]:
    """Resolve human-facing policy names while sealed labels stay stable."""

    schema = str(comparisons_doc.get("schema") or "")
    if schema == "scene_dna_guard_blind_comparisons_v1":
        return {
            "experiment_kind": "form_guard_hidden_validation",
            "report_title": "SceneDNA 第二轮形态门隐藏盲评结果",
            "control_label": str(
                comparisons_doc.get("control_method")
                or "current_hard_eligible_combined_selector"
            ),
            "treatment_label": str(
                comparisons_doc.get("proposed_method")
                or "form_improvement_guard_0.08"
            ),
            "conditional_estimand": str(
                comparisons_doc.get("conditional_estimand")
                or "cases_where_guard_changes_the_selected_candidate"
            ),
            "is_guard_round": True,
        }
    return {
        "experiment_kind": "candidate_selector_hidden_validation",
        "report_title": "SceneDNA 三评审冻结结果",
        "control_label": "baseline",
        "treatment_label": "proposed",
        "conditional_estimand": "frozen_pairwise_candidate_preference",
        "is_guard_round": False,
    }


def _score_facets(row: dict[str, Any]) -> dict[str, float | None]:
    score = row.get("score") if isinstance(row.get("score"), dict) else {}
    semantic = score.get("semantic") if isinstance(score.get("semantic"), dict) else {}
    form = score.get("form") if isinstance(score.get("form"), dict) else {}
    combined = score.get("combined") if isinstance(score.get("combined"), dict) else {}
    facets = combined.get("facets") if isinstance(combined.get("facets"), dict) else {}
    pixel = facets.get("pixel_style") if isinstance(facets.get("pixel_style"), dict) else {}

    def number(value: Any) -> float | None:
        return round(float(value), 6) if isinstance(value, (int, float)) else None

    return {
        "combined": number(score.get("score")),
        "semantic": number(semantic.get("score")),
        "form": number(form.get("score")),
        "pixel_style": number(pixel.get("score", score.get("legacy_pixel_score"))),
    }


def _case_automatic_scores(
    case_id: str,
    comparison: dict[str, Any],
    candidate_root: Path,
) -> dict[str, Any]:
    batch = read_json(candidate_root / case_id / "candidate_batch_result.json")
    ranking = (
        batch.get("scene_dna_candidate_selection", {}).get("ranking", [])
        if isinstance(batch.get("scene_dna_candidate_selection"), dict)
        else []
    )
    by_asset = {
        str(row.get("reference_job_id") or ""): row
        for row in ranking
        if isinstance(row, dict)
    }
    eligible_rows = [row for row in ranking if isinstance(row, dict) and row.get("eligible")]
    methods: dict[str, Any] = {}
    for method in ("baseline", "proposed"):
        asset_id = str(comparison.get(method, {}).get("asset_id") or "")
        ranked = by_asset.get(asset_id)
        methods[method] = {
            "asset_id": asset_id,
            "found_in_ranking": ranked is not None,
            "rank": ranked.get("rank") if ranked else None,
            "eligible": ranked.get("eligible") if ranked else None,
            "scores": _score_facets(ranked or {}),
        }
    deltas: dict[str, float | None] = {}
    for metric in ("combined", "semantic", "form", "pixel_style"):
        baseline = methods["baseline"]["scores"][metric]
        proposed = methods["proposed"]["scores"][metric]
        deltas[metric] = (
            round(float(proposed) - float(baseline), 6)
            if baseline is not None and proposed is not None
            else None
        )
    current_combined = max(
        eligible_rows,
        key=lambda row: float((row.get("score") or {}).get("score", -1.0)),
    )
    current_legacy = max(
        eligible_rows,
        key=lambda row: float((row.get("score") or {}).get("legacy_pixel_score", -1.0)),
    )
    combined_form = _score_facets(current_combined)["form"]
    legacy_form = _score_facets(current_legacy)["form"]
    current_form_delta = (
        float(combined_form) - float(legacy_form)
        if combined_form is not None and legacy_form is not None
        else None
    )
    guarded = (
        current_combined
        if current_combined is current_legacy
        or (
            current_form_delta is not None
            and current_form_delta >= 0.08
        )
        else current_legacy
    )
    proposed_id = methods["proposed"]["asset_id"]
    baseline_id = methods["baseline"]["asset_id"]

    def relation(row: dict[str, Any]) -> str:
        asset_id = str(row.get("reference_job_id") or "")
        if asset_id == proposed_id:
            return "frozen_proposed"
        if asset_id == baseline_id:
            return "frozen_baseline"
        return "other_unlabeled_candidate"

    return {
        "methods": methods,
        "proposed_minus_baseline": deltas,
        "current_candidate_snapshot": {
            "combined_selector_reference_job_id": current_combined.get(
                "reference_job_id"
            ),
            "combined_selector_relation_to_frozen_pair": relation(current_combined),
            "legacy_control_reference_job_id": current_legacy.get("reference_job_id"),
            "legacy_control_relation_to_frozen_pair": relation(current_legacy),
            "guarded_selector_reference_job_id": guarded.get("reference_job_id"),
            "guarded_selector_relation_to_frozen_pair": relation(guarded),
            "combined_minus_legacy_form_score": (
                round(current_form_delta, 6) if current_form_delta is not None else None
            ),
        },
    }


def replay_form_guard_on_candidate_root(
    candidate_root: Path,
    *,
    minimum_form_improvement: float = 0.08,
) -> dict[str, Any]:
    benchmark_path = candidate_root.parent / "candidate_benchmark_results.json"
    category_by_case: dict[str, str] = {}
    if benchmark_path.is_file():
        benchmark = read_json(benchmark_path)
        category_by_case = {
            str(row.get("case_id") or ""): str(row.get("category") or "unknown")
            for row in benchmark.get("results", [])
            if isinstance(row, dict)
        }
    rows: list[dict[str, Any]] = []
    for case_dir in sorted(candidate_root.glob("case_*")):
        batch_path = case_dir / "candidate_batch_result.json"
        if not batch_path.is_file():
            continue
        batch = read_json(batch_path)
        selection = batch.get("scene_dna_candidate_selection")
        selection = selection if isinstance(selection, dict) else {}
        eligible = [
            row
            for row in selection.get("ranking", [])
            if isinstance(row, dict) and row.get("eligible")
        ]
        if not eligible:
            rows.append(
                {
                    "case_id": case_dir.name,
                    "category": category_by_case.get(case_dir.name, "unknown"),
                    "status": "no_eligible_candidate",
                }
            )
            continue
        combined = max(
            eligible,
            key=lambda row: float((row.get("score") or {}).get("score", -1.0)),
        )
        legacy = max(
            eligible,
            key=lambda row: float(
                (row.get("score") or {}).get("legacy_pixel_score", -1.0)
            ),
        )
        combined_form = _score_facets(combined)["form"]
        legacy_form = _score_facets(legacy)["form"]
        delta = (
            float(combined_form) - float(legacy_form)
            if combined_form is not None and legacy_form is not None
            else None
        )
        accepted = bool(
            combined is legacy
            or delta is not None
            and delta >= float(minimum_form_improvement)
        )
        selected = combined if accepted else legacy
        rows.append(
            {
                "case_id": case_dir.name,
                "category": category_by_case.get(case_dir.name, "unknown"),
                "status": "evaluated",
                "combined_reference_job_id": combined.get("reference_job_id"),
                "legacy_reference_job_id": legacy.get("reference_job_id"),
                "guarded_reference_job_id": selected.get("reference_job_id"),
                "combined_and_legacy_same": combined is legacy,
                "combined_minus_legacy_form_score": (
                    round(delta, 6) if delta is not None else None
                ),
                "decision": (
                    "same_candidate"
                    if combined is legacy
                    else "keep_combined"
                    if accepted
                    else "fallback_to_legacy"
                ),
                "guarded_candidate_is_eligible": selected in eligible,
            }
        )
    evaluated = [row for row in rows if row.get("status") == "evaluated"]
    decisions = Counter(str(row.get("decision")) for row in evaluated)
    by_category: dict[str, Any] = {}
    for category in sorted({str(row["category"]) for row in evaluated}):
        category_rows = [row for row in evaluated if row["category"] == category]
        by_category[category] = {
            "case_count": len(category_rows),
            "decision_counts": dict(
                Counter(str(row["decision"]) for row in category_rows)
            ),
        }
    return {
        "schema": "scene_dna_form_guard_candidate_root_replay_v1",
        "candidate_root": str(candidate_root.resolve()),
        "minimum_form_improvement": float(minimum_form_improvement),
        "category_specific_branching": False,
        "case_count": len(rows),
        "evaluated_case_count": len(evaluated),
        "decision_counts": dict(decisions),
        "all_guarded_candidates_eligible": all(
            row["guarded_candidate_is_eligible"] for row in evaluated
        ),
        "by_category": by_category,
        "cases": rows,
        "efficacy_claim_allowed": False,
        "reason": "Offline selector-behavior audit only; it contains no new human labels.",
    }


def archive_and_analyze(
    response_paths: list[Path],
    *,
    public_trials_path: Path,
    sealed_key_path: Path,
    comparisons_path: Path,
    candidate_root: Path,
    output_dir: Path,
    paired_3d_report_path: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=False)
    public = read_json(public_trials_path)
    sealed = read_json(sealed_key_path)
    comparisons_doc = read_json(comparisons_path)
    experiment_context = _experiment_context(comparisons_doc)
    public_by_trial = {
        str(row["trial_id"]): row for row in public.get("trials", []) if isinstance(row, dict)
    }
    key_by_trial = {
        str(row["trial_id"]): row for row in sealed.get("trials", []) if isinstance(row, dict)
    }
    expected_ids = list(public_by_trial)
    if set(expected_ids) != set(key_by_trial):
        raise ValueError("public trial ids and sealed-key trial ids differ")
    comparisons = {
        str(row["case_id"]): row
        for row in comparisons_doc.get("comparisons", [])
        if isinstance(row, dict)
    }

    anonymized: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    original_reviewer_ids: set[str] = set()
    for index, response_path in enumerate(response_paths, 1):
        rows = _read_jsonl(response_path)
        ids = [str(row.get("trial_id") or "") for row in rows]
        reviewers = {str(row.get("reviewer_id") or "") for row in rows}
        if len(reviewers) != 1 or "" in reviewers or "anonymous" in reviewers:
            raise ValueError(f"{response_path}: requires one stable non-anonymous reviewer id")
        original_id = next(iter(reviewers))
        if original_id in original_reviewer_ids:
            raise ValueError(f"duplicate reviewer id across files: {original_id}")
        original_reviewer_ids.add(original_id)
        if ids != expected_ids:
            raise ValueError(f"{response_path}: trial ids/order do not match frozen bundle")
        for row in rows:
            status = str(row.get("trial_quality_status") or "ok")
            if status not in {"ok", "flagged"}:
                raise ValueError(f"{response_path}: invalid quality status {status}")
            if status == "ok":
                for axis in AXES:
                    if str(row.get(f"{axis}_choice") or "") not in CHOICES:
                        raise ValueError(f"{response_path}: invalid {axis} choice")
            derived = dict(row)
            derived["reviewer_id"] = f"reviewer_{index:02d}"
            anonymized.append(derived)
        elapsed = [float(row.get("elapsed_seconds", 0.0) or 0.0) for row in rows]
        sources.append(
            {
                "derived_reviewer_id": f"reviewer_{index:02d}",
                "source_basename": response_path.name,
                "source_sha256": _sha256(response_path),
                "source_size_bytes": response_path.stat().st_size,
                "response_count": len(rows),
                "quality_flagged_count": sum(
                    str(row.get("trial_quality_status") or "ok") == "flagged" for row in rows
                ),
                "elapsed_total_seconds": round(sum(elapsed), 3),
                "elapsed_median_seconds": round(statistics.median(elapsed), 3),
            }
        )
    anonymous_path = output_dir / "responses_anonymized.jsonl"
    _write_jsonl(anonymous_path, anonymized)
    manifest = {
        "schema": "scene_dna_review_archive_manifest_v1",
        "raw_sources_modified": False,
        "reviewer_identity_values_persisted": False,
        "frozen_public_trials_sha256": _sha256(public_trials_path),
        "sealed_key_sha256": _sha256(sealed_key_path),
        "comparison_sha256": _sha256(comparisons_path),
        "anonymized_responses_sha256": _sha256(anonymous_path),
        "reviewer_count": len(response_paths),
        "submitted_response_count": len(anonymized),
        "sources": sources,
    }
    write_json(output_dir / "archive_manifest.json", manifest)
    official = analyze_responses(
        anonymous_path,
        sealed_key_path,
        output_dir / "official_blind_analysis.json",
    )

    outcome_rows: list[dict[str, Any]] = []
    for response in anonymized:
        if str(response.get("trial_quality_status") or "ok") == "flagged":
            continue
        trial_id = str(response["trial_id"])
        trial = key_by_trial[trial_id]
        public_trial = public_by_trial[trial_id]
        for axis in AXES:
            choice = str(response[f"{axis}_choice"])
            outcome = (
                str(trial["assets"][choice]["method"])
                if choice in {"left", "right"}
                else choice
            )
            outcome_rows.append(
                {
                    "trial_id": trial_id,
                    "case_id": str(trial.get("independent_case_id") or trial["case_id"]),
                    "reviewer_id": str(response["reviewer_id"]),
                    "category": str(public_trial.get("category") or "unknown"),
                    "axis": axis,
                    "outcome": outcome,
                    "preference_value": _preference_value(outcome),
                }
            )

    case_axis: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in outcome_rows:
        case_axis[(row["case_id"], row["axis"])].append(row)
    case_reports: list[dict[str, Any]] = []
    case_ids = sorted({row["case_id"] for row in outcome_rows})
    auto_by_case: dict[str, Any] = {}
    for case_id in case_ids:
        comparison = comparisons[case_id]
        automatic = _case_automatic_scores(case_id, comparison, candidate_root)
        auto_by_case[case_id] = automatic
        axes: dict[str, Any] = {}
        for axis in AXES:
            rows = case_axis[(case_id, axis)]
            counts = Counter(str(row["outcome"]) for row in rows)
            values = [float(row["preference_value"]) for row in rows if row["preference_value"] is not None]
            axes[axis] = {
                "outcome_counts_including_repeats": dict(counts),
                "preference_rating_count": len(values),
                "preference_rate_ties_half_neither_excluded": (
                    round(statistics.fmean(values), 6) if values else None
                ),
            }
        case_reports.append(
            {
                "case_id": case_id,
                "category": str(comparison.get("category") or "unknown"),
                "human": axes,
                "automatic_2d": automatic,
            }
        )

    category_reports: dict[str, Any] = {}
    categories = sorted({row["category"] for row in case_reports})
    for category in categories:
        cases = [row for row in case_reports if row["category"] == category]
        axis_summary: dict[str, Any] = {}
        for axis in AXES:
            values = [
                float(row["human"][axis]["preference_rate_ties_half_neither_excluded"])
                for row in cases
                if row["human"][axis]["preference_rate_ties_half_neither_excluded"] is not None
            ]
            axis_summary[axis] = {
                "independent_case_count": len(values),
                "preference_rate_ties_half_neither_excluded": (
                    round(statistics.fmean(values), 6) if values else None
                ),
                "descriptive_bootstrap_95pct_interval": _bootstrap_interval(values),
            }
        category_reports[category] = {"case_count": len(cases), "axes": axis_summary}

    repeat_by_reviewer: dict[str, Any] = {}
    for reviewer in sorted({row["reviewer_id"] for row in outcome_rows}):
        repeat_by_reviewer[reviewer] = {}
        for axis in AXES:
            groups: dict[str, list[str]] = defaultdict(list)
            for row in outcome_rows:
                if row["reviewer_id"] == reviewer and row["axis"] == axis:
                    groups[row["case_id"]].append(row["outcome"])
            checks = [
                outcomes[0] == other
                for outcomes in groups.values()
                if len(outcomes) > 1
                for other in outcomes[1:]
            ]
            repeat_by_reviewer[reviewer][axis] = (
                round(sum(checks) / len(checks), 6) if checks else None
            )

    metric_alignment: dict[str, Any] = {}
    for metric in ("combined", "semantic", "form", "pixel_style"):
        for human_axis in ("semantic", "form", "style", "overall"):
            automatic_values: list[float] = []
            human_values: list[float] = []
            agreement: list[bool] = []
            for row in case_reports:
                delta = row["automatic_2d"]["proposed_minus_baseline"][metric]
                human = row["human"][human_axis]["preference_rate_ties_half_neither_excluded"]
                if delta is None or human is None:
                    continue
                automatic_values.append(float(delta))
                human_values.append(float(human) - 0.5)
                if abs(float(delta)) > 1e-12 and abs(float(human) - 0.5) > 1e-12:
                    agreement.append((float(delta) > 0.0) == (float(human) > 0.5))
            metric_alignment[f"{metric}_vs_{human_axis}"] = {
                "case_count": len(automatic_values),
                "pearson_delta_correlation": _pearson(automatic_values, human_values),
                "directional_agreement_rate_excluding_ties": (
                    round(sum(agreement) / len(agreement), 6) if agreement else None
                ),
                "directional_comparison_count": len(agreement),
            }

    guard_threshold = 0.08
    guard_case_rows: list[dict[str, Any]] = []
    for row in case_reports:
        form_delta = row["automatic_2d"]["proposed_minus_baseline"]["form"]
        combined_delta = row["automatic_2d"]["proposed_minus_baseline"]["combined"]
        select_proposed = bool(
            form_delta is not None
            and combined_delta is not None
            and float(form_delta) >= guard_threshold
            and float(combined_delta) >= 0.0
        )
        semantic = row["human"]["semantic"][
            "preference_rate_ties_half_neither_excluded"
        ]
        form = row["human"]["form"][
            "preference_rate_ties_half_neither_excluded"
        ]
        human_primary = (
            statistics.fmean([float(semantic), float(form)])
            if semantic is not None and form is not None
            else None
        )
        guard_case_rows.append(
            {
                "case_id": row["case_id"],
                "category": row["category"],
                "selected_method": "proposed" if select_proposed else "legacy_control",
                "form_score_delta": form_delta,
                "combined_score_delta": combined_delta,
                "observed_primary_value_vs_legacy_control": (
                    round(float(human_primary), 6)
                    if select_proposed and human_primary is not None
                    else 0.5
                ),
            }
        )
    guard_values = [
        float(row["observed_primary_value_vs_legacy_control"])
        for row in guard_case_rows
    ]
    guard_categories: dict[str, Any] = {}
    for category in categories:
        rows = [row for row in guard_case_rows if row["category"] == category]
        guard_categories[category] = {
            "case_count": len(rows),
            "proposed_selection_count": sum(
                row["selected_method"] == "proposed" for row in rows
            ),
            "development_replay_primary_value": round(
                statistics.fmean(
                    float(row["observed_primary_value_vs_legacy_control"])
                    for row in rows
                ),
                6,
            ),
        }
    frozen_pairwise_guard_replay = {
        "schema": "scene_dna_form_improvement_guard_replay_v1",
        "policy": {
            "category_specific_branching": False,
            "minimum_form_improvement": guard_threshold,
            "minimum_combined_improvement": 0.0,
            "fallback": "legacy_control",
        },
        "selected_proposed_case_count": sum(
            row["selected_method"] == "proposed" for row in guard_case_rows
        ),
        "total_case_count": len(guard_case_rows),
        "frozen_data_replay_primary_value": round(statistics.fmean(guard_values), 6),
        "frozen_data_replay_bootstrap_95pct_interval": _bootstrap_interval(guard_values),
        "current_all_proposed_primary_value": official[
            "primary_semantic_form_preference_rate"
        ],
        "category_reports": guard_categories,
        "case_decisions": guard_case_rows,
        "efficacy_claim_allowed": False,
        "reason": (
            "This replays only the two frozen labeled assets, while the current candidate "
            "snapshot can select a third unlabeled candidate. The threshold was also selected "
            "after inspecting this development dataset; new hidden seeds, candidate batches, "
            "and reviewers are required."
        ),
    }
    current_guard_relations = Counter(
        row["automatic_2d"]["current_candidate_snapshot"][
            "guarded_selector_relation_to_frozen_pair"
        ]
        for row in case_reports
    )
    current_guard_scorable_values: list[float] = []
    for row in case_reports:
        relation = row["automatic_2d"]["current_candidate_snapshot"][
            "guarded_selector_relation_to_frozen_pair"
        ]
        if relation == "frozen_baseline":
            current_guard_scorable_values.append(0.5)
        elif relation == "frozen_proposed":
            semantic = row["human"]["semantic"][
                "preference_rate_ties_half_neither_excluded"
            ]
            form = row["human"]["form"][
                "preference_rate_ties_half_neither_excluded"
            ]
            if semantic is not None and form is not None:
                current_guard_scorable_values.append(
                    statistics.fmean([float(semantic), float(form)])
                )
    current_snapshot_guard_audit = {
        "guarded_selection_relation_counts": dict(current_guard_relations),
        "frozen_pair_scorable_case_count": len(current_guard_scorable_values),
        "other_unlabeled_candidate_count": current_guard_relations.get(
            "other_unlabeled_candidate", 0
        ),
        "partial_scorable_primary_value": (
            round(statistics.fmean(current_guard_scorable_values), 6)
            if current_guard_scorable_values
            else None
        ),
        "efficacy_claim_allowed": False,
        "reason": (
            "The frozen reviewers did not rate current third-candidate selections; partial "
            "coverage cannot be promoted to a full-policy estimate."
        ),
    }
    full_candidate_guard_replay = replay_form_guard_on_candidate_root(candidate_root)

    three_d = read_json(paired_3d_report_path) if paired_3d_report_path else None
    three_d_join: list[dict[str, Any]] = []
    if three_d:
        human_cases = {row["case_id"]: row for row in case_reports}
        for row in three_d.get("results", []):
            case_id = str(row.get("case_id") or "")
            human = human_cases.get(case_id)
            if human is None:
                continue
            feasibility = row.get("feasibility") if isinstance(row.get("feasibility"), dict) else {}
            three_d_join.append(
                {
                    "case_id": case_id,
                    "category": row.get("category"),
                    "human_2d_semantic": human["human"]["semantic"]["preference_rate_ties_half_neither_excluded"],
                    "human_2d_form": human["human"]["form"]["preference_rate_ties_half_neither_excluded"],
                    "baseline_3d_usable": feasibility.get("baseline", {}).get("usable_for_scene_assembly"),
                    "proposed_3d_usable": feasibility.get("proposed", {}).get("usable_for_scene_assembly"),
                    "automated_3d_verdict": row.get("comparison", {}).get("automated_verdict"),
                }
            )

    extended = {
        "schema": "scene_dna_three_reviewer_extended_analysis_v1",
        "experiment_context": experiment_context,
        "official_analysis_path": str(output_dir / "official_blind_analysis.json"),
        "category_results_are_descriptive_not_independently_powered": True,
        "category_reports": category_reports,
        "case_reports": case_reports,
        "repeat_agreement_by_anonymous_reviewer": repeat_by_reviewer,
        "automatic_2d_human_alignment": metric_alignment,
        "frozen_pairwise_form_guard_replay": frozen_pairwise_guard_replay,
        "current_snapshot_form_guard_audit": current_snapshot_guard_audit,
        "full_candidate_root_form_guard_replay": full_candidate_guard_replay,
        "human_2d_to_automated_3d_join": three_d_join,
        "claim_boundary": (
            "This dataset may diagnose the frozen benchmark, but any tuned selector requires "
            "new held-out seeds and reviewers before an efficacy claim."
        ),
    }
    write_json(output_dir / "extended_analysis.json", extended)
    markdown_lines = [
        f"# {experiment_context['report_title']}",
        "",
        "## 正式结论",
        "",
        f"- 有效评审者：{len(response_paths)}",
        f"- 独立 case：{official['axes']['semantic']['independent_trial_count']}",
        f"- 对照方法：`{experiment_context['control_label']}`",
        f"- 实验方法：`{experiment_context['treatment_label']}`",
        f"- 条件估计范围：`{experiment_context['conditional_estimand']}`",
        f"- 实验方法语义偏好率：{official['axes']['semantic']['proposed_preference_rate_ties_half']:.6f}",
        "- 语义 case-clustered 95% CI："
        f"{official['axes']['semantic']['cluster_bootstrap_95pct_interval']}",
        f"- 实验方法形态偏好率：{official['axes']['form']['proposed_preference_rate_ties_half']:.6f}",
        "- 形态 case-clustered 95% CI："
        f"{official['axes']['form']['cluster_bootstrap_95pct_interval']}",
        f"- 主要指标：{official['primary_semantic_form_preference_rate']:.6f}",
        f"- 图片异常题：{official['quality_flagged_response_count']}",
        f"- 四维隐藏重复一致率：{official['reviewer_repeat_exact_agreement_rate']:.6f}",
        f"- 预注册门槛通过：{str(official['primary_gate_passed']).lower()}",
        "- 默认流程替换：不允许",
        "",
        "`neither` 表示两个候选都不可用，已从偏好率分母排除；`tie` 继续按 0.5 计。",
        "",
        "## 类别诊断（描述性）",
        "",
        "| 类别 | case | 语义 | 形态 | 风格 | 综合 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category, row in category_reports.items():
        markdown_lines.append(
            "| "
            + " | ".join(
                [
                    category,
                    str(row["case_count"]),
                    *[
                        f"{row['axes'][axis]['preference_rate_ties_half_neither_excluded']:.6f}"
                        for axis in AXES
                    ],
                ]
            )
            + " |"
        )
    markdown_lines.extend(
        [
            "",
            "类别样本仅 3–5 个，以上结果用于失败归因，不作为独立显著性结论。",
            "",
            "## 自动评分对人工判断",
            "",
            "- SigLIP 语义差值与人工语义偏好的相关系数："
            f"{metric_alignment['semantic_vs_semantic']['pearson_delta_correlation']}",
            "- 形态差值与人工形态偏好的相关系数："
            f"{metric_alignment['form_vs_form']['pearson_delta_correlation']}",
            "- 现有 combined 差值与人工综合偏好的相关系数："
            f"{metric_alignment['combined_vs_overall']['pearson_delta_correlation']}",
            "",
        ]
    )
    if experiment_context["is_guard_round"]:
        markdown_lines.extend(
            [
                "本轮形态分差与人工形态偏好呈负相关；现有 `0.08` 形态改善门没有获得隐藏数据支持，"
                "不得打开或替换当前选择器。自动分仍可作诊断和硬失败筛查，但不能作为本轮候选替换依据。",
                "",
                "## 决策",
                "",
                "- 保持形态改善门默认关闭。",
                "- 因 2D 必要门槛已经失败，不为晋级目的继续执行本轮 3D non-regression；这不会影响"
                "既有 3D 诊断，但本轮不具备推广资格。",
                "- 类别差异只用于定位失败，不据此启用类别特判；下一版选择器必须使用新的开发样本，"
                "并再用全新 seed 和评审者做隐藏验证。",
            ]
        )
    else:
        markdown_lines.extend(
            [
                "本轮数据表明，形态证据可保留为正向选择依据；零样本语义与像素风格分暂时只适合"
                "作诊断/硬门辅助，不能单独推动替换。",
                "",
                "## 开发期保守门",
                "",
                (
                    "冻结两候选回放值："
                    f"{frozen_pairwise_guard_replay['frozen_data_replay_primary_value']:.6f}；"
                    "选择 proposed "
                    f"{frozen_pairwise_guard_replay['selected_proposed_case_count']} / "
                    f"{frozen_pairwise_guard_replay['total_case_count']}。"
                ),
                "",
                "该阈值是在查看本轮标签后提出，且当前候选池有第三候选未被旧评审覆盖，因此只能作为"
                "下一轮隐藏数据的实验分支，不能用本轮回放宣称收益。",
            ]
        )
    report_markdown_path = output_dir / "REPORT.md"
    report_markdown_path.write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")
    summary = {
        "schema": "scene_dna_three_reviewer_analysis_summary_v1",
        "archive_valid": True,
        "reviewer_count": len(response_paths),
        "independent_case_count": official["axes"]["semantic"]["independent_trial_count"],
        "primary_preference_rate": official["primary_semantic_form_preference_rate"],
        "primary_gate_passed": official["primary_gate_passed"],
        "default_pipeline_replacement_allowed": False,
        "experiment_context": experiment_context,
        "official_analysis": str(output_dir / "official_blind_analysis.json"),
        "extended_analysis": str(output_dir / "extended_analysis.json"),
        "human_readable_report": str(report_markdown_path),
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", action="append", required=True, type=Path)
    parser.add_argument("--public-trials", required=True, type=Path)
    parser.add_argument("--sealed-key", required=True, type=Path)
    parser.add_argument("--comparisons", required=True, type=Path)
    parser.add_argument("--candidate-root", required=True, type=Path)
    parser.add_argument("--paired-3d-report", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = archive_and_analyze(
        list(args.response),
        public_trials_path=args.public_trials,
        sealed_key_path=args.sealed_key,
        comparisons_path=args.comparisons,
        candidate_root=args.candidate_root,
        paired_3d_report_path=args.paired_3d_report,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
