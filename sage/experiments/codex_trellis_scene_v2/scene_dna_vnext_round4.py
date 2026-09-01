from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .brief import build_asset_generation_spec, render_asset_prompt
from .io_utils import read_json, write_json
from .scene_dna_benchmark import HELDOUT_ROUND2_CATEGORIES, STYLE_CONDITIONS
from .scene_dna_vnext_pilot import analyze_vnext_pilot
from .scene_dna_vnext_round3 import extract_vnext_comparisons, freeze_vnext_artifacts


ROUND4_PREFLIGHT_CATEGORIES = tuple(HELDOUT_ROUND2_CATEGORIES)


def _candidate_seeds(plan: dict[str, Any]) -> set[int]:
    return {
        int(seed)
        for batch in plan.get("batches", [])
        if isinstance(batch, dict)
        for seed in batch.get("candidate_seeds", [])
    }


def _assert_seed_isolation(
    plan: dict[str, Any], previous_plan_paths: Iterable[Path]
) -> dict[str, Any]:
    current = _candidate_seeds(plan)
    expected = sum(
        len(batch.get("candidate_seeds", []))
        for batch in plan.get("batches", [])
        if isinstance(batch, dict)
    )
    if len(current) != expected:
        raise ValueError("candidate seeds must be globally unique within the new plan")
    overlaps: dict[str, list[int]] = {}
    checked: list[str] = []
    for path in previous_plan_paths:
        resolved = Path(path).resolve()
        previous = read_json(resolved)
        overlap = sorted(current & _candidate_seeds(previous))
        checked.append(str(resolved))
        if overlap:
            overlaps[str(resolved)] = overlap
    if overlaps:
        raise ValueError(f"new plan reuses frozen candidate seeds: {overlaps}")
    return {
        "globally_unique_candidate_seed_count": len(current),
        "previous_plan_paths_checked": checked,
        "previous_seed_overlap_count": 0,
    }


def _build_batches(
    *,
    prefix: str,
    provenance: str,
    base_seed: int,
    category_conditions: Iterable[tuple[str, dict[str, Any]]],
    seeds_per_category_style: int,
    candidate_count: int,
) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    independent_index = 0
    for category, condition in category_conditions:
        dimensions = deepcopy(HELDOUT_ROUND2_CATEGORIES[category])
        prompt = (
            f"A {condition['id'].replace('_', ' ')} room requiring one "
            f"{category.replace('_', ' ')} in {condition['appearance']}."
        )
        obj = {
            "id": f"{prefix}_{category}_{condition['id']}",
            "category": category,
            "dimensions": deepcopy(dimensions),
            "requested_dimensions": deepcopy(dimensions),
            "provenance": provenance,
        }
        spec = build_asset_generation_spec(obj, list(condition["styles"]), prompt)
        for _seed_index in range(int(seeds_per_category_style)):
            batch_seed = int(base_seed) + independent_index * 100_003
            payload = {
                "category": category,
                "style_condition": condition["id"],
                "object_prompt": render_asset_prompt(spec),
                "semantic_form_contract": deepcopy(spec["semantic_form_contract"]),
                "requested_dimensions": deepcopy(dimensions),
                "batch_seed": batch_seed,
                "candidate_seeds": [
                    batch_seed + offset * 9_973
                    for offset in range(int(candidate_count))
                ],
                "candidate_count": int(candidate_count),
            }
            case_id = prefix + "_" + hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode("utf-8")
            ).hexdigest()[:12]
            batches.append({"case_id": case_id, **payload})
            independent_index += 1
    return batches


def build_round4_preflight_plan(
    output_dir: Path,
    *,
    base_seed: int = 2026102801,
    candidate_count: int = 4,
    previous_plan_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Freeze one batch per formal category as non-efficacy engineering data."""

    conditions = [
        (category, STYLE_CONDITIONS[index % len(STYLE_CONDITIONS)])
        for index, category in enumerate(ROUND4_PREFLIGHT_CATEGORIES)
    ]
    batches = _build_batches(
        prefix="round4_preflight",
        provenance="scene_dna_vnext_round4_alpha_provenance_preflight",
        base_seed=base_seed,
        category_conditions=conditions,
        seeds_per_category_style=1,
        candidate_count=candidate_count,
    )
    plan = {
        "schema": "scene_dna_vnext_round4_preflight_plan_v1",
        "frozen_before_generation": True,
        "independent_from_formal_round4": True,
        "must_never_enter_human_efficacy_questionnaire": True,
        "base_seed": int(base_seed),
        "batch_count": len(batches),
        "candidate_count_per_batch": int(candidate_count),
        "candidate_image_count": len(batches) * int(candidate_count),
        "categories": list(ROUND4_PREFLIGHT_CATEGORIES),
        "engineering_gates": {
            "all_batches_complete": True,
            "fixed_neutral_generation_background_fraction": 1.0,
            "review_eligible_alpha_chroma_hygiene_pass_fraction": 1.0,
            "every_batch_has_generability_eligible_candidate": True,
            "selector_must_change_at_least_one_case": True,
        },
        "batches": batches,
    }
    plan["seed_isolation"] = _assert_seed_isolation(plan, previous_plan_paths)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "scene_dna_vnext_round4_preflight_plan.json", plan)
    return plan


def analyze_round4_preflight(
    plan_path: Path, candidate_root: Path, output_path: Path
) -> dict[str, Any]:
    report = analyze_vnext_pilot(plan_path, candidate_root, output_path)
    report["schema"] = "scene_dna_vnext_round4_preflight_analysis_v1"
    report["formal_round4_images_generated"] = False
    report["next_decision"] = (
        "eligible_to_freeze_all_new_seed_formal_round4"
        if report["engineering_gates_passed"]
        else "repair_on_independent_engineering_data_before_formal_round4"
    )
    write_json(output_path, report)
    return report


def build_round4_plan(
    output_dir: Path,
    *,
    preflight_report_path: Path,
    base_seed: int = 2026112801,
    seeds_per_category_style: int = 5,
    candidate_count: int = 4,
    previous_plan_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """Freeze formal round four only after the independent preflight passes."""

    preflight_path = preflight_report_path.resolve()
    preflight = read_json(preflight_path)
    if not bool(preflight.get("engineering_gates_passed")):
        raise ValueError("round4 preflight gates did not pass")
    category_conditions = [
        (category, condition)
        for category in HELDOUT_ROUND2_CATEGORIES
        for condition in STYLE_CONDITIONS
    ]
    batches = _build_batches(
        prefix="round4",
        provenance="scene_dna_vnext_round4_heldout",
        base_seed=base_seed,
        category_conditions=category_conditions,
        seeds_per_category_style=seeds_per_category_style,
        candidate_count=candidate_count,
    )
    plan = {
        "schema": "scene_dna_vnext_round4_plan_v1",
        "frozen_before_generation": True,
        "created_without_round4_human_labels": True,
        "independent_preflight_passed_before_freeze": True,
        "preflight_report_path": str(preflight_path),
        "preflight_report_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
        "base_seed": int(base_seed),
        "category_count": len(HELDOUT_ROUND2_CATEGORIES),
        "style_condition_count": len(STYLE_CONDITIONS),
        "seeds_per_category_style": int(seeds_per_category_style),
        "candidate_count_per_batch": int(candidate_count),
        "batch_count": len(batches),
        "candidate_image_count": len(batches) * int(candidate_count),
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
            "preflight images and seeds are engineering-only and never enter the formal questionnaire",
            "2D pass is necessary but not sufficient; paired same-seed 3D non-regression follows",
            "selector rescue cases without a valid current control are reported but excluded from pairwise human efficacy",
        ],
    }
    plan["seed_isolation"] = _assert_seed_isolation(plan, previous_plan_paths)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "scene_dna_vnext_round4_plan.json", plan)
    return plan


def freeze_round4_artifacts(
    round_root: Path,
    *,
    previous_public_trials: tuple[Path, ...] = (),
    previous_plan_paths: tuple[Path, ...] = (),
) -> dict[str, Any]:
    """Validate and hash the isolated round-four public questionnaire."""

    return freeze_vnext_artifacts(
        round_root,
        round_label="round4",
        previous_public_trials=previous_public_trials,
        previous_plan_paths=previous_plan_paths,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight-plan")
    preflight.add_argument("--output-dir", required=True, type=Path)
    preflight.add_argument("--base-seed", type=int, default=2026102801)
    preflight.add_argument("--candidate-count", type=int, default=4)
    preflight.add_argument("--previous-plan", action="append", default=[], type=Path)
    analyze = subparsers.add_parser("analyze-preflight")
    analyze.add_argument("--plan", required=True, type=Path)
    analyze.add_argument("--candidate-root", required=True, type=Path)
    analyze.add_argument("--output", required=True, type=Path)
    formal = subparsers.add_parser("formal-plan")
    formal.add_argument("--output-dir", required=True, type=Path)
    formal.add_argument("--preflight-report", required=True, type=Path)
    formal.add_argument("--base-seed", type=int, default=2026112801)
    formal.add_argument("--seeds-per-category-style", type=int, default=5)
    formal.add_argument("--candidate-count", type=int, default=4)
    formal.add_argument("--previous-plan", action="append", default=[], type=Path)
    extract = subparsers.add_parser("extract")
    extract.add_argument("--plan", required=True, type=Path)
    extract.add_argument("--candidate-root", required=True, type=Path)
    extract.add_argument("--output-dir", required=True, type=Path)
    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--round-root", required=True, type=Path)
    freeze.add_argument(
        "--previous-public-trials", action="append", default=[], type=Path
    )
    freeze.add_argument("--previous-plan", action="append", default=[], type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "preflight-plan":
        report = build_round4_preflight_plan(
            args.output_dir,
            base_seed=args.base_seed,
            candidate_count=args.candidate_count,
            previous_plan_paths=args.previous_plan,
        )
    elif args.command == "analyze-preflight":
        report = analyze_round4_preflight(args.plan, args.candidate_root, args.output)
    elif args.command == "formal-plan":
        report = build_round4_plan(
            args.output_dir,
            preflight_report_path=args.preflight_report,
            base_seed=args.base_seed,
            seeds_per_category_style=args.seeds_per_category_style,
            candidate_count=args.candidate_count,
            previous_plan_paths=args.previous_plan,
        )
    elif args.command == "extract":
        report = extract_vnext_comparisons(
            args.plan, args.candidate_root, args.output_dir, round_label="round4"
        )
    else:
        report = freeze_round4_artifacts(
            args.round_root,
            previous_public_trials=tuple(args.previous_public_trials),
            previous_plan_paths=tuple(args.previous_plan),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
