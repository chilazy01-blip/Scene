from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from PIL import Image

from .alpha_hygiene import (
    audit_sanitized_alpha_edges,
    clean_chromatic_alpha_edges,
    recorded_alpha_background_rgb,
)
from .brief import build_asset_generation_spec, render_asset_prompt
from .io_utils import read_json, write_json
from .scene_dna_benchmark import HELDOUT_ROUND2_CATEGORIES, STYLE_CONDITIONS


def _attempt_alpha_background_rgb(attempt: dict[str, Any]) -> list[float] | None:
    """Read the private source-matte provenance recorded by the bridge."""

    return recorded_alpha_background_rgb(attempt.get("alpha_metadata"))


def build_round3_plan(
    output_dir: Path,
    *,
    base_seed: int = 2026090101,
    seeds_per_category_style: int = 5,
    candidate_count: int = 4,
) -> dict[str, Any]:
    """Pre-register the clean held-out vNext comparison before generation."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    batches: list[dict[str, Any]] = []
    independent_batch_index = 0
    for category, dimensions in HELDOUT_ROUND2_CATEGORIES.items():
        for condition in STYLE_CONDITIONS:
            prompt = (
                f"A {condition['id'].replace('_', ' ')} room requiring one "
                f"{category.replace('_', ' ')} in {condition['appearance']}."
            )
            obj = {
                "id": f"round3_{category}_{condition['id']}",
                "category": category,
                "dimensions": deepcopy(dimensions),
                "requested_dimensions": deepcopy(dimensions),
                "provenance": "scene_dna_vnext_round3_heldout",
            }
            spec = build_asset_generation_spec(
                obj, list(condition["styles"]), prompt
            )
            for seed_index in range(int(seeds_per_category_style)):
                batch_seed = int(base_seed) + independent_batch_index * 100_003
                payload = {
                    "category": category,
                    "style_condition": condition["id"],
                    "object_prompt": render_asset_prompt(spec),
                    "semantic_form_contract": deepcopy(
                        spec["semantic_form_contract"]
                    ),
                    "requested_dimensions": deepcopy(dimensions),
                    "batch_seed": batch_seed,
                    "candidate_seeds": [
                        batch_seed + offset * 9_973
                        for offset in range(int(candidate_count))
                    ],
                    "candidate_count": int(candidate_count),
                }
                case_id = "round3_" + hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode("utf-8")
                ).hexdigest()[:12]
                batches.append({"case_id": case_id, **payload})
                independent_batch_index += 1
    all_candidate_seeds = [
        int(seed) for batch in batches for seed in batch["candidate_seeds"]
    ]
    if len(set(all_candidate_seeds)) != len(all_candidate_seeds):
        raise ValueError("round3 candidate seeds must be globally unique")
    plan = {
        "schema": "scene_dna_vnext_round3_plan_v1",
        "frozen_before_generation": True,
        "created_without_round3_human_labels": True,
        "base_seed": int(base_seed),
        "category_count": len(HELDOUT_ROUND2_CATEGORIES),
        "style_condition_count": len(STYLE_CONDITIONS),
        "seeds_per_category_style": int(seeds_per_category_style),
        "candidate_count_per_batch": int(candidate_count),
        "batch_count": len(batches),
        "candidate_image_count": len(batches) * int(candidate_count),
        "globally_unique_candidate_seed_count": len(set(all_candidate_seeds)),
        "categories": list(HELDOUT_ROUND2_CATEGORIES),
        "comparison": {
            "control_method": "current_hard_eligible_semantic_form_style_selector",
            "proposed_method": "scene_dna_vnext_balanced_generability_v1",
            "conditional_estimand": "cases_where_both_selectors_are_hard_eligible_and_choose_different_candidates",
            "category_specific_branching": False,
            "old_form_guard_used": False,
        },
        "freeze_gates": {
            "completed_independent_batch_count": len(batches),
            "minimum_changed_comparable_cases": 30,
            "maximum_questionnaire_independent_cases": 50,
            "selected_pair_image_hygiene_pass_fraction": 1.0,
            "fixed_neutral_background_fraction": 1.0,
            "minimum_hidden_repeat_fraction": 0.10,
            "left_right_balance_required": True,
            "default_pipeline_replacement_before_human_and_3d_pass_forbidden": True,
        },
        "analysis_policy": {
            "tie_credit": 0.5,
            "neither_excluded_from_pairwise_preference_denominator": True,
            "cluster_bootstrap_unit": "independent_case",
            "primary_axes": ["semantic", "form"],
            "primary_value": "mean_of_semantic_and_form_pairwise_preference",
            "minimum_primary_value": 0.60,
            "confidence_interval_lower_bound_must_exceed": 0.50,
        },
        "batches": batches,
        "limitations": [
            "2D pass is necessary but not sufficient; paired same-seed 3D non-regression follows",
            "selector rescue cases without a valid current control are reported but excluded from pairwise human efficacy",
        ],
    }
    write_json(output_dir / "scene_dna_vnext_round3_plan.json", plan)
    return plan


def extract_vnext_comparisons(
    plan_path: Path,
    candidate_root: Path,
    output_dir: Path,
    *,
    round_label: str = "round3",
) -> dict[str, Any]:
    """Freeze all comparable changed cases, with deterministic cap at 50."""

    plan = read_json(plan_path)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    changed: list[dict[str, Any]] = []
    rescue: list[dict[str, Any]] = []
    missing: list[str] = []
    rejected: list[dict[str, Any]] = []
    selected_hygiene_failures: list[dict[str, Any]] = []
    completed = 0
    fixed_background_count = 0
    selected_image_count = 0
    for batch in plan.get("batches", []):
        case_id = str(batch["case_id"])
        result_path = candidate_root / "cases" / case_id / "candidate_batch_result.json"
        failure_path = candidate_root / "cases" / case_id / "candidate_batch_failure.json"
        if not result_path.is_file():
            if failure_path.is_file():
                failure = read_json(failure_path)
                completed += 1
                rejected.append(
                    {
                        "case_id": case_id,
                        "category": batch.get("category"),
                        "reason": "candidate_batch_rejected_or_failed",
                        "error": failure.get("error"),
                    }
                )
                continue
            missing.append(case_id)
            continue
        completed += 1
        result = read_json(result_path)
        selection = result.get("scene_dna_candidate_selection") or {}
        current_id = selection.get("combined_selector_reference_job_id")
        vnext_id = selection.get("vnext_selector_reference_job_id")
        attempts = {
            str(item.get("reference_job_id")): item
            for item in result.get("reference_attempts", [])
            if isinstance(item, dict)
        }
        if not current_id and vnext_id:
            rescue.append(
                {
                    "case_id": case_id,
                    "category": batch.get("category"),
                    "vnext_reference_job_id": vnext_id,
                    "reason": "current_selector_has_no_hard_eligible_candidate",
                }
            )
            ids_to_audit = [vnext_id]
        elif current_id and vnext_id and current_id != vnext_id:
            ids_to_audit = [current_id, vnext_id]
        else:
            ids_to_audit = [identifier for identifier in (current_id, vnext_id) if identifier]
        hygiene_by_id: dict[str, bool] = {}
        for identifier in dict.fromkeys(ids_to_audit):
            attempt = attempts.get(str(identifier))
            if not attempt:
                selected_hygiene_failures.append(
                    {"case_id": case_id, "reference_job_id": identifier, "reason": "attempt_missing"}
                )
                hygiene_by_id[str(identifier)] = False
                continue
            selected_image_count += 1
            fixed = attempt.get("background") == "simple solid light gray background"
            fixed_background_count += int(fixed)
            image_path = Path(str(attempt.get("prepared_image_path") or ""))
            if image_path.is_file():
                background_rgb = _attempt_alpha_background_rgb(attempt)
                if background_rgb is None:
                    _, hygiene = clean_chromatic_alpha_edges(Image.open(image_path))
                else:
                    hygiene = audit_sanitized_alpha_edges(
                        Image.open(image_path), background_rgb
                    )
                ok = bool(hygiene.get("ok")) and fixed
            else:
                hygiene = {"ok": False, "reasons": ["prepared_image_missing"]}
                ok = False
            hygiene_by_id[str(identifier)] = ok
            if not ok:
                selected_hygiene_failures.append(
                    {
                        "case_id": case_id,
                        "reference_job_id": identifier,
                        "fixed_neutral_background": fixed,
                        "hygiene": hygiene,
                    }
                )
        if current_id and vnext_id and current_id != vnext_id:
            if not (hygiene_by_id.get(str(current_id)) and hygiene_by_id.get(str(vnext_id))):
                continue
            changed.append(
                {
                    "case_id": case_id,
                    "category": batch["category"],
                    "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                    "object_requirement": batch["object_prompt"],
                    "style_requirement": batch["style_condition"],
                    "baseline": {
                        "asset_id": current_id,
                        "image_path": attempts[str(current_id)]["prepared_image_path"],
                        "alpha_hygiene_background_rgb": _attempt_alpha_background_rgb(
                            attempts[str(current_id)]
                        ),
                    },
                    "proposed": {
                        "asset_id": vnext_id,
                        "image_path": attempts[str(vnext_id)]["prepared_image_path"],
                        "alpha_hygiene_background_rgb": _attempt_alpha_background_rgb(
                            attempts[str(vnext_id)]
                        ),
                    },
                }
            )
    # If more than 50 cases change, use a deterministic hash order.  This is
    # independent of image scores, category labels, and future human answers.
    changed.sort(
        key=lambda row: hashlib.sha256(
            str(row["case_id"]).encode("utf-8")
        ).hexdigest()
    )
    cap = int(plan["freeze_gates"]["maximum_questionnaire_independent_cases"])
    frozen = changed[:cap]
    minimum = int(plan["freeze_gates"]["minimum_changed_comparable_cases"])
    hygiene_fraction = (
        1.0 - len(selected_hygiene_failures) / max(1, selected_image_count)
    )
    background_fraction = fixed_background_count / max(1, selected_image_count)
    freeze_passed = bool(
        completed == int(plan["batch_count"])
        and len(frozen) >= minimum
        and not selected_hygiene_failures
        and background_fraction == 1.0
    )
    comparisons = {
        "schema": f"scene_dna_vnext_{round_label}_blind_comparisons_v1",
        "control_method": plan["comparison"]["control_method"],
        "proposed_method": plan["comparison"]["proposed_method"],
        "conditional_estimand": plan["comparison"]["conditional_estimand"],
        "comparisons": frozen,
    }
    write_json(output_dir / "blind_comparisons.json", comparisons)
    report = {
        "schema": f"scene_dna_vnext_{round_label}_extraction_v1",
        "plan_path": str(plan_path.resolve()),
        "candidate_root": str(candidate_root.resolve()),
        "completed_batch_count": completed,
        "missing_case_ids": missing,
        "rejected_batch_count": len(rejected),
        "rejected_batches": rejected,
        "changed_comparable_case_count_before_cap": len(changed),
        "frozen_independent_case_count": len(frozen),
        "rescue_without_current_control_count": len(rescue),
        "rescue_cases": rescue,
        "selected_image_count": selected_image_count,
        "selected_pair_image_hygiene_pass_fraction": round(hygiene_fraction, 6),
        "fixed_neutral_background_fraction": round(background_fraction, 6),
        "selected_hygiene_failures": selected_hygiene_failures,
        "freeze_gates_passed": freeze_passed,
        "decision": (
            f"eligible_to_build_{round_label}_blind_bundle"
            if freeze_passed
            else f"do_not_build_{round_label}_questionnaire"
        ),
        "comparisons_path": str(output_dir / "blind_comparisons.json"),
    }
    write_json(output_dir / "extraction_report.json", report)
    return report


def extract_round3_comparisons(
    plan_path: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    return extract_vnext_comparisons(
        plan_path,
        candidate_root,
        output_dir,
        round_label="round3",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_vnext_artifacts(
    round_root: Path,
    *,
    round_label: str,
    previous_public_trials: tuple[Path, ...] = (),
    previous_plan_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Validate and hash one public vNext questionnaire release."""

    round_root = round_root.resolve()
    if round_label not in {"round3", "round4"}:
        raise ValueError(f"unsupported vNext freeze label: {round_label}")
    plan_path = round_root / f"scene_dna_vnext_{round_label}_plan.json"
    extraction_path = round_root / f"{round_label}_extraction" / "extraction_report.json"
    comparison_path = round_root / f"{round_label}_extraction" / "blind_comparisons.json"
    public_bundle = round_root / f"blind_review_bundle_2d_{round_label}"
    public_trials_path = public_bundle / "trials.json"
    sealed_key_path = round_root / f"sealed_blind_key_2d_{round_label}.json"
    offline_path = round_root / f"SceneDNA_blind_review_2D_{round_label}_offline.html"
    audit_path = round_root / f"{round_label}_image_audit.json"
    required = (
        plan_path,
        extraction_path,
        comparison_path,
        public_trials_path,
        sealed_key_path,
        offline_path,
        audit_path,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing {round_label} artifacts: {missing}")
    plan = read_json(plan_path)
    extraction = read_json(extraction_path)
    public = read_json(public_trials_path)
    key = read_json(sealed_key_path)
    audit = read_json(audit_path)
    if not extraction.get("freeze_gates_passed"):
        raise ValueError(f"{round_label} extraction freeze gates did not pass")
    if not audit.get("strict_bundle_passed"):
        raise ValueError(f"{round_label} public image audit did not pass")
    public_trials = public.get("trials", [])
    key_trials = key.get("trials", [])
    if len(public_trials) != len(key_trials) or not public_trials:
        raise ValueError("public/key trial count mismatch or empty questionnaire")
    independent = [row for row in key_trials if not row.get("duplicate_of_trial_id")]
    repeats = [row for row in key_trials if row.get("duplicate_of_trial_id")]
    if len(independent) != int(extraction["frozen_independent_case_count"]):
        raise ValueError("independent trial count does not match extraction")
    minimum_repeats = math.ceil(
        len(independent)
        * float(plan["freeze_gates"]["minimum_hidden_repeat_fraction"])
    )
    if len(repeats) < minimum_repeats:
        raise ValueError("hidden repeat count is below the pre-registered minimum")
    public_text = json.dumps(public, ensure_ascii=False).lower()
    leaked = [
        token
        for token in ("baseline", "proposed", "current_selector", "vnext_selector")
        if token in public_text
    ]
    if leaked:
        raise ValueError(f"method labels leaked into public trials: {leaked}")
    image_paths: list[Path] = []
    proposed_sides: Counter[str] = Counter()
    for key_row in independent:
        for side in ("left", "right"):
            if key_row["assets"][side]["method"] == "proposed":
                proposed_sides[side] += 1
    if abs(proposed_sides["left"] - proposed_sides["right"]) > 1:
        raise ValueError("independent proposed-side assignment is not balanced")
    for row in public_trials:
        for side in ("left", "right"):
            relative = Path(str(row["assets"][side]["image_path"]))
            image_path = (public_bundle / relative).resolve()
            if public_bundle not in image_path.parents or not image_path.is_file():
                raise ValueError(f"invalid public image path: {relative}")
            with Image.open(image_path) as image:
                if image.mode != "RGB" or image.width < 256 or image.height < 256:
                    raise ValueError(f"non-standard public image: {image_path}")
            image_paths.append(image_path)
    current_case_ids = {str(row.get("case_id") or "") for row in public_trials}
    current_image_hashes = {_sha256(path) for path in image_paths}
    previous_case_overlap: set[str] = set()
    previous_image_overlap: set[str] = set()
    for previous_path in previous_public_trials:
        previous_path = previous_path.resolve()
        previous = read_json(previous_path)
        previous_rows = previous.get("trials", [])
        previous_case_overlap.update(
            current_case_ids
            & {str(row.get("case_id") or "") for row in previous_rows}
        )
        previous_bundle = previous_path.parent
        previous_hashes = {
            _sha256((previous_bundle / row["assets"][side]["image_path"]).resolve())
            for row in previous_rows
            for side in ("left", "right")
        }
        previous_image_overlap.update(current_image_hashes & previous_hashes)
    current_seeds = {
        int(seed) for batch in plan["batches"] for seed in batch["candidate_seeds"]
    }
    previous_seed_overlap: set[int] = set()
    for previous_plan_path in previous_plan_paths:
        previous_plan = read_json(previous_plan_path.resolve())
        previous_seeds = {
            int(seed)
            for batch in previous_plan.get("batches", [])
            for seed in batch.get("candidate_seeds", [])
        }
        previous_seed_overlap.update(current_seeds & previous_seeds)
    if previous_case_overlap or previous_image_overlap or previous_seed_overlap:
        raise ValueError(f"{round_label} overlaps a previous frozen experiment")
    positions = {str(row["trial_id"]): index for index, row in enumerate(key_trials)}
    repeat_distance = min(
        (
            abs(
                positions[str(row["trial_id"])]
                - positions[str(row["duplicate_of_trial_id"])]
            )
            for row in repeats
        ),
        default=None,
    )
    independent_trial_ids = {str(row["trial_id"]) for row in independent}
    manifest = {
        "schema": f"scene_dna_vnext_{round_label}_freeze_manifest_v1",
        "frozen": True,
        "public_share_only": str(offline_path),
        "sealed_key_private": str(sealed_key_path),
        "method_labels_hidden_from_public": True,
        "scores_hidden_from_public": True,
        "independent_trial_count": len(independent),
        "hidden_repeat_count": len(repeats),
        "total_trial_count": len(public_trials),
        "category_counts": dict(
            Counter(
                str(row.get("category") or "")
                for row in public_trials
                if str(row["trial_id"]) in independent_trial_ids
            )
        ),
        "proposed_side_balance_independent": dict(proposed_sides),
        "hidden_repeat_minimum_position_distance": repeat_distance,
        "public_image_count": len(image_paths),
        "public_unique_image_sha256_count": len(current_image_hashes),
        "previous_round_case_overlap_count": len(previous_case_overlap),
        "previous_round_image_sha256_overlap_count": len(previous_image_overlap),
        "previous_round_candidate_seed_overlap_count": len(previous_seed_overlap),
        "candidate_batch_count": int(extraction["completed_batch_count"]),
        "candidate_batch_rejection_count": int(extraction["rejected_batch_count"]),
        "changed_comparable_case_count_before_cap": int(
            extraction["changed_comparable_case_count_before_cap"]
        ),
        "selected_pair_image_hygiene_pass_fraction": extraction[
            "selected_pair_image_hygiene_pass_fraction"
        ],
        "fixed_neutral_background_fraction": extraction[
            "fixed_neutral_background_fraction"
        ],
        "efficacy_claim_allowed_before_new_human_analysis": False,
        "sha256": {
            "plan": _sha256(plan_path),
            "extraction_report": _sha256(extraction_path),
            "blind_comparisons_private": _sha256(comparison_path),
            "public_trials": _sha256(public_trials_path),
            "sealed_key_private": _sha256(sealed_key_path),
            "offline_html_public": _sha256(offline_path),
            "image_audit": _sha256(audit_path),
        },
    }
    write_json(round_root / "FREEZE_MANIFEST.json", manifest)
    chinese_round = {"round3": "第三轮", "round4": "第四轮"}[round_label]
    offline_name = offline_path.name
    readme = (
        f"# SceneDNA vNext {chinese_round}离线匿名评审\n\n"
        f"只把 `{offline_name}` 发给评审者；"
        "不要发送本目录、sealed key、候选结果、分数或联系表。\n\n"
        "评审者在本机浏览器双击 HTML，填写不含姓名的稳定编号，独立完成全部题目，"
        "最后下载 JSONL。请把原始 JSONL 原样放入 `/data/wsj/main/test`，不要手工修改。\n"
    )
    (round_root / "README_REVIEWERS.md").write_text(readme, encoding="utf-8")
    return manifest


def freeze_round3_artifacts(
    round_root: Path,
    *,
    previous_public_trials: tuple[Path, ...] = (),
    previous_plan_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Backward-compatible round-three freeze entry point."""

    return freeze_vnext_artifacts(
        round_root,
        round_label="round3",
        previous_public_trials=previous_public_trials,
        previous_plan_paths=previous_plan_paths,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--output-dir", required=True, type=Path)
    plan_parser.add_argument("--base-seed", type=int, default=2026090101)
    plan_parser.add_argument("--seeds-per-category-style", type=int, default=5)
    plan_parser.add_argument("--candidate-count", type=int, default=4)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--plan", required=True, type=Path)
    extract_parser.add_argument("--candidate-root", required=True, type=Path)
    extract_parser.add_argument("--output-dir", required=True, type=Path)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--round-root", required=True, type=Path)
    freeze_parser.add_argument(
        "--previous-public-trials", action="append", default=[], type=Path
    )
    freeze_parser.add_argument(
        "--previous-plan", action="append", default=[], type=Path
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        report = build_round3_plan(
            args.output_dir,
            base_seed=args.base_seed,
            seeds_per_category_style=args.seeds_per_category_style,
            candidate_count=args.candidate_count,
        )
    elif args.command == "extract":
        report = extract_round3_comparisons(
            args.plan, args.candidate_root, args.output_dir
        )
    else:
        report = freeze_round3_artifacts(
            args.round_root,
            previous_public_trials=tuple(args.previous_public_trials),
            previous_plan_paths=tuple(args.previous_plan),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
