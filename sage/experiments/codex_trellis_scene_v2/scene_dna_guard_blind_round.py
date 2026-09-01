from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .io_utils import read_json, write_json


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_candidate_image(
    candidate_root: Path,
    case_id: str,
    attempt: dict[str, Any],
) -> Path:
    copied = (
        candidate_root
        / "cases"
        / case_id
        / f"candidate_{int(attempt.get('attempt', 0)):02d}.png"
    )
    if copied.is_file():
        return copied.resolve()
    source = Path(str(attempt.get("prepared_image_path") or ""))
    if source.is_file():
        return source.resolve()
    raise FileNotFoundError(
        f"missing candidate image for {case_id} attempt {attempt.get('attempt')}"
    )


def build_guard_blind_comparisons(
    plan_path: Path,
    candidate_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Extract held-out current-selector versus form-guard comparisons.

    Only cases where the two selectors choose different hard-eligible images are
    exposed to reviewers.  This estimates the effect on decisions changed by the
    guard; it is not an unconditional average over all generated batches.
    """

    plan_path = plan_path.resolve()
    candidate_root = candidate_root.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = read_json(plan_path)
    if not bool(plan.get("frozen_before_generation")):
        raise ValueError("benchmark plan is not marked frozen before generation")
    if plan.get("category_set") != "heldout_round2":
        raise ValueError("guard blind extraction requires heldout_round2 category set")
    if float(plan.get("form_guard_threshold_frozen_before_generation")) != 0.08:
        raise ValueError("unexpected form guard threshold in frozen plan")

    batch_by_case = {
        str(item["case_id"]): item
        for item in plan.get("batches", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    comparisons: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    decision_counts: Counter[str] = Counter()
    category_changed_counts: Counter[str] = Counter()
    category_evaluated_counts: Counter[str] = Counter()
    for case_id, batch in batch_by_case.items():
        result_path = candidate_root / "cases" / case_id / "candidate_batch_result.json"
        failure_path = candidate_root / "cases" / case_id / "candidate_batch_failure.json"
        if not result_path.is_file():
            decision_counts["batch_failed"] += 1
            cases.append(
                {
                    "case_id": case_id,
                    "category": batch["category"],
                    "status": "batch_failed",
                    "failure_path": str(failure_path) if failure_path.is_file() else None,
                }
            )
            continue
        bridge_result = read_json(result_path)
        selection = bridge_result.get("scene_dna_candidate_selection")
        if not isinstance(selection, dict):
            raise ValueError(f"missing selection report for {case_id}")
        guard = selection.get("selection_guard")
        if not isinstance(guard, dict) or not guard.get("enabled"):
            raise ValueError(f"form guard was not enabled for {case_id}")
        if bool(guard.get("category_specific_branching")):
            raise ValueError(f"category-specific guard branching found for {case_id}")
        control_id = str(selection.get("combined_selector_reference_job_id") or "")
        treatment_id = str(selection.get("selected_reference_job_id") or "")
        if not control_id or not treatment_id:
            raise ValueError(f"missing selector identities for {case_id}")
        attempts = {
            str(item.get("reference_job_id") or ""): item
            for item in bridge_result.get("reference_attempts", [])
            if isinstance(item, dict)
        }
        ranking = {
            str(item.get("reference_job_id") or ""): item
            for item in selection.get("ranking", [])
            if isinstance(item, dict)
        }
        if control_id not in attempts or treatment_id not in attempts:
            raise ValueError(f"selector image missing for {case_id}")
        if not ranking.get(control_id, {}).get("eligible"):
            raise ValueError(f"current control is not hard eligible for {case_id}")
        if not ranking.get(treatment_id, {}).get("eligible"):
            raise ValueError(f"guard treatment is not hard eligible for {case_id}")
        category = str(batch["category"])
        category_evaluated_counts[category] += 1
        changed = control_id != treatment_id
        decision = "changed_by_guard" if changed else "same_candidate"
        decision_counts[decision] += 1
        case_report = {
            "case_id": case_id,
            "category": category,
            "style_condition": batch["style_condition"],
            "batch_seed": int(batch["batch_seed"]),
            "status": decision,
            "current_control_reference_job_id": control_id,
            "guard_treatment_reference_job_id": treatment_id,
            "guard_decision": guard.get("decision"),
            "form_score_delta": guard.get("form_score_delta"),
            "both_hard_eligible": True,
        }
        cases.append(case_report)
        if not changed:
            continue
        category_changed_counts[category] += 1
        control_path = _stable_candidate_image(
            candidate_root, case_id, attempts[control_id]
        )
        treatment_path = _stable_candidate_image(
            candidate_root, case_id, attempts[treatment_id]
        )
        comparisons.append(
            {
                "case_id": case_id,
                "category": category,
                "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                "object_requirement": batch["object_prompt"],
                "style_requirement": batch["style_condition"],
                "baseline": {
                    "asset_id": control_id,
                    "image_path": str(control_path),
                },
                "proposed": {
                    "asset_id": treatment_id,
                    "image_path": str(treatment_path),
                },
            }
        )

    comparison_path = output_dir / "blind_comparisons.json"
    write_json(
        comparison_path,
        {
            "schema": "scene_dna_guard_blind_comparisons_v1",
            "control_method": "current_hard_eligible_combined_selector",
            "proposed_method": "form_improvement_guard_0.08",
            "conditional_estimand": "cases_where_guard_changes_the_selected_candidate",
            "comparisons": comparisons,
        },
    )
    report = {
        "schema": "scene_dna_guard_blind_round_extraction_v1",
        "plan_path": str(plan_path),
        "plan_sha256": _sha256(plan_path),
        "candidate_root": str(candidate_root),
        "planned_batch_count": len(batch_by_case),
        "evaluated_batch_count": sum(category_evaluated_counts.values()),
        "blind_independent_case_count": len(comparisons),
        "decision_counts": dict(decision_counts),
        "category_evaluated_counts": dict(category_evaluated_counts),
        "category_changed_counts": dict(category_changed_counts),
        "all_compared_candidates_hard_eligible": all(
            item.get("both_hard_eligible") for item in cases if item["status"] != "batch_failed"
        ),
        "category_specific_branching": False,
        "form_guard_threshold": 0.08,
        "efficacy_claim_allowed_before_new_human_analysis": False,
        "conditional_estimand": "human preference on cases changed by the guard",
        "cases": cases,
        "blind_comparisons_path": str(comparison_path),
    }
    write_json(output_dir / "extraction_report.json", report)
    return report


def write_private_contact_sheet(
    comparisons_path: Path,
    output_path: Path,
    *,
    cell_size: int = 360,
) -> dict[str, Any]:
    comparisons = read_json(comparisons_path).get("comparisons", [])
    rows: list[Image.Image] = []
    font = ImageFont.load_default()
    for index, item in enumerate(comparisons, start=1):
        canvas = Image.new("RGB", (cell_size * 2, cell_size + 44), "#eeeeee")
        draw = ImageDraw.Draw(canvas)
        for column, method in enumerate(("baseline", "proposed")):
            source = Image.open(item[method]["image_path"]).convert("RGBA")
            backdrop = Image.new("RGBA", source.size, "#d8d8d8")
            backdrop.alpha_composite(source)
            image = backdrop.convert("RGB")
            image.thumbnail((cell_size - 12, cell_size - 12))
            x = column * cell_size + (cell_size - image.width) // 2
            y = 38 + (cell_size - image.height) // 2
            canvas.paste(image, (x, y))
        draw.text(
            (8, 8),
            f"{index:02d} {item['category']} {item['case_id']} | control / guard",
            fill="black",
            font=font,
        )
        rows.append(canvas)
    if not rows:
        raise ValueError("no comparisons available for contact sheet")
    sheet = Image.new("RGB", (cell_size * 2, sum(row.height for row in rows)), "white")
    y = 0
    for row in rows:
        sheet.paste(row, (0, y))
        y += row.height
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, optimize=True)
    return {
        "schema": "scene_dna_guard_private_contact_sheet_v1",
        "comparison_count": len(rows),
        "output_path": str(output_path),
        "sha256": _sha256(output_path),
    }


def freeze_round_artifacts(
    round_root: Path,
    *,
    old_public_trials: Path | None = None,
) -> dict[str, Any]:
    round_root = round_root.resolve()
    plan_path = round_root / "scene_dna_benchmark_plan.json"
    extraction_path = round_root / "guard_blind_extraction_v1" / "extraction_report.json"
    comparison_path = round_root / "guard_blind_extraction_v1" / "blind_comparisons.json"
    public_bundle = round_root / "blind_review_bundle_2d_beta"
    public_trials_path = public_bundle / "trials.json"
    sealed_key_path = round_root / "sealed_blind_key_2d_beta.json"
    offline_path = round_root / "SceneDNA_blind_review_2D_beta_offline.html"
    required = (
        plan_path,
        extraction_path,
        comparison_path,
        public_trials_path,
        sealed_key_path,
        offline_path,
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing round artifacts: {missing}")
    plan = read_json(plan_path)
    extraction = read_json(extraction_path)
    public = read_json(public_trials_path)
    key = read_json(sealed_key_path)
    trials = public.get("trials", [])
    key_trials = key.get("trials", [])
    if len(trials) != len(key_trials):
        raise ValueError("public/key trial count mismatch")
    independent_keys = [item for item in key_trials if not item.get("duplicate_of_trial_id")]
    repeat_keys = [item for item in key_trials if item.get("duplicate_of_trial_id")]
    if len(independent_keys) != extraction["blind_independent_case_count"]:
        raise ValueError("independent trial count does not match extraction")
    public_serialized = json.dumps(public, ensure_ascii=False).lower()
    leaked_tokens = [
        token
        for token in ("baseline", "proposed", "current_control", "form_guard")
        if token in public_serialized
    ]
    if leaked_tokens:
        raise ValueError(f"method tokens leaked into public trials: {leaked_tokens}")
    image_paths: list[Path] = []
    for trial in trials:
        for side in ("left", "right"):
            path = (public_bundle / trial["assets"][side]["image_path"]).resolve()
            if public_bundle not in path.parents or not path.is_file():
                raise ValueError(f"invalid public image: {path}")
            with Image.open(path) as image:
                if image.width < 256 or image.height < 256:
                    raise ValueError(f"undersized public image: {path}")
                if image.getbbox() is None:
                    raise ValueError(f"empty public image: {path}")
            image_paths.append(path)
    proposed_sides = Counter()
    for item in independent_keys:
        for side in ("left", "right"):
            if item["assets"][side]["method"] == "proposed":
                proposed_sides[side] += 1
    positions = {item["trial_id"]: index for index, item in enumerate(key_trials)}
    repeat_minimum_distance = min(
        (
            abs(positions[item["trial_id"]] - positions[item["duplicate_of_trial_id"]])
            for item in repeat_keys
        ),
        default=None,
    )
    old_trial_overlap: list[str] = []
    old_image_hash_overlap: list[str] = []
    if old_public_trials is not None:
        old_public_trials = old_public_trials.resolve()
        old_public = read_json(old_public_trials)
        old_case_ids = {
            str(item.get("case_id") or "") for item in old_public.get("trials", [])
        }
        old_trial_overlap = sorted(
            {str(item.get("case_id") or "") for item in trials} & old_case_ids
        )
        old_bundle = old_public_trials.parent
        old_hashes = {
            _sha256((old_bundle / item["assets"][side]["image_path"]).resolve())
            for item in old_public.get("trials", [])
            for side in ("left", "right")
        }
        old_image_hash_overlap = sorted({_sha256(path) for path in image_paths} & old_hashes)
    if old_trial_overlap or old_image_hash_overlap:
        raise ValueError("round two overlaps the previous public trial set")
    manifest = {
        "schema": "scene_dna_guard_blind_round2_freeze_manifest_v1",
        "frozen": True,
        "public_share_only": str(offline_path),
        "public_bundle": str(public_bundle),
        "sealed_key_private": str(sealed_key_path),
        "method_labels_hidden_from_public": True,
        "scores_hidden_from_public": True,
        "left_right_randomized": True,
        "trial_order_randomized": True,
        "new_generation_seed_family": int(plan["batches"][0]["batch_seed"]),
        "question_random_seed": int(key["random_seed"]),
        "planned_batch_count": int(extraction["planned_batch_count"]),
        "evaluated_batch_count": int(extraction["evaluated_batch_count"]),
        "failed_batch_count": int(extraction["decision_counts"].get("batch_failed", 0)),
        "independent_trial_count": len(independent_keys),
        "hidden_repeat_count": len(repeat_keys),
        "total_trial_count": len(trials),
        "category_counts": dict(Counter(item["category"] for item in trials if item["trial_id"] in {key_item["trial_id"] for key_item in independent_keys})),
        "proposed_side_balance_independent": dict(proposed_sides),
        "hidden_repeat_minimum_position_distance": repeat_minimum_distance,
        "public_image_count": len(image_paths),
        "public_unique_image_sha256_count": len({_sha256(path) for path in image_paths}),
        "previous_round_case_overlap_count": len(old_trial_overlap),
        "previous_round_image_sha256_overlap_count": len(old_image_hash_overlap),
        "all_compared_candidates_hard_eligible": bool(
            extraction["all_compared_candidates_hard_eligible"]
        ),
        "conditional_estimand": extraction["conditional_estimand"],
        "efficacy_claim_allowed_before_new_human_analysis": False,
        "sha256": {
            "plan": _sha256(plan_path),
            "extraction_report": _sha256(extraction_path),
            "blind_comparisons_private": _sha256(comparison_path),
            "public_trials": _sha256(public_trials_path),
            "sealed_key_private": _sha256(sealed_key_path),
            "offline_html_public": _sha256(offline_path),
        },
        "limitations": [
            "The human estimand is conditional on batches where the guard changes the selected candidate.",
            "Accent-chair batches all failed the frozen form gate and therefore do not appear in the questionnaire.",
            "Storage-box, bookcase, and floor-lamp had no changed hard-eligible pairs and therefore do not appear in the questionnaire.",
            "No efficacy claim is permitted before independent hidden-label human analysis and 3D non-regression checks.",
        ],
    }
    write_json(round_root / "FREEZE_MANIFEST.json", manifest)
    reviewer_readme = """# SceneDNA 第二轮离线匿名评审\n\n请只把 `SceneDNA_blind_review_2D_beta_offline.html` 发给评审者，不要发送本目录中的其他文件。\n\n评审者在本机浏览器中双击 HTML，填写不含姓名的稳定编号，完成全部 20 题后点击“下载最终结果 JSONL”。请独立作答，不查看文件源码，不讨论候选来源。若图片未加载、主体被裁断或显示异常，请使用“图片异常，跳过本题”。\n\n收回的 JSONL 请原样放入 `/data/wsj/main/test`，不要手工修改。\n"""
    (round_root / "README_REVIEWERS.md").write_text(reviewer_readme, encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract")
    extract.add_argument("--plan", required=True, type=Path)
    extract.add_argument("--candidate-root", required=True, type=Path)
    extract.add_argument("--output-dir", required=True, type=Path)
    sheet = sub.add_parser("contact-sheet")
    sheet.add_argument("--comparisons", required=True, type=Path)
    sheet.add_argument("--output", required=True, type=Path)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--round-root", required=True, type=Path)
    freeze.add_argument("--old-public-trials", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        report = build_guard_blind_comparisons(
            args.plan, args.candidate_root, args.output_dir
        )
    elif args.command == "contact-sheet":
        report = write_private_contact_sheet(args.comparisons, args.output)
    else:
        report = freeze_round_artifacts(
            args.round_root, old_public_trials=args.old_public_trials
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
