from __future__ import annotations

import argparse
import hashlib
import json
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
from .scene_dna_vnext import assess_2d_generability, select_vnext_candidate


PILOT_CATEGORIES = (
    "storage_box",
    "bookcase",
    "book_stack",
    "office_chair",
    "table_lamp",
    "potted_plant",
    "slipper",
    "accent_chair",
)


def build_vnext_pilot_plan(
    output_dir: Path,
    *,
    base_seed: int = 2026082607,
    candidate_count: int = 4,
) -> dict[str, Any]:
    """Freeze a small new-seed engineering pilot before any image is generated."""

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    batches: list[dict[str, Any]] = []
    for index, category in enumerate(PILOT_CATEGORIES):
        dimensions = deepcopy(HELDOUT_ROUND2_CATEGORIES[category])
        condition = STYLE_CONDITIONS[index % len(STYLE_CONDITIONS)]
        prompt = (
            f"A {condition['id'].replace('_', ' ')} room requiring one "
            f"{category.replace('_', ' ')} in {condition['appearance']}."
        )
        obj = {
            "id": f"vnext_pilot_{category}",
            "category": category,
            "dimensions": deepcopy(dimensions),
            "requested_dimensions": deepcopy(dimensions),
            "provenance": "scene_dna_vnext_new_seed_engineering_pilot",
        }
        spec = build_asset_generation_spec(
            obj, list(condition["styles"]), prompt
        )
        batch_seed = int(base_seed) + index * 100_003
        payload = {
            "category": category,
            "style_condition": condition["id"],
            "object_prompt": render_asset_prompt(spec),
            "semantic_form_contract": deepcopy(spec["semantic_form_contract"]),
            "requested_dimensions": dimensions,
            "batch_seed": batch_seed,
            "candidate_seeds": [
                batch_seed + offset * 9_973 for offset in range(candidate_count)
            ],
            "candidate_count": int(candidate_count),
        }
        case_id = "vnext_" + hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        batches.append({"case_id": case_id, **payload})
    plan = {
        "schema": "scene_dna_vnext_engineering_pilot_plan_v1",
        "frozen_before_generation": True,
        "created_without_human_label_access": True,
        "base_seed": int(base_seed),
        "candidate_count_per_batch": int(candidate_count),
        "batch_count": len(batches),
        "candidate_image_count": len(batches) * int(candidate_count),
        "categories": list(PILOT_CATEGORIES),
        "selection_comparison": {
            "control": "semantic_form_style_v1_current_selector",
            "treatment": "balanced_generability_vnext_v1",
            "category_specific_branching": False,
        },
        "engineering_gates": {
            "all_batches_complete": True,
            "fixed_neutral_generation_background_fraction": 1.0,
            "review_eligible_alpha_chroma_hygiene_pass_fraction": 1.0,
            "every_batch_has_generability_eligible_candidate": True,
            "selector_must_change_at_least_one_case": True,
        },
        "prohibited_claims": [
            "engineering gates alone do not prove human preference improvement",
            "this small pilot is not the frozen third-round blind evaluation",
        ],
        "batches": batches,
    }
    write_json(output_dir / "scene_dna_vnext_pilot_plan.json", plan)
    return plan


def analyze_vnext_pilot(plan_path: Path, candidate_root: Path, output_path: Path) -> dict[str, Any]:
    plan = read_json(plan_path)
    rows: list[dict[str, Any]] = []
    hygiene_rows: list[dict[str, Any]] = []
    for batch in plan.get("batches", []):
        case_id = str(batch["case_id"])
        result_path = candidate_root / "cases" / case_id / "candidate_batch_result.json"
        if not result_path.is_file():
            rows.append({"case_id": case_id, "status": "missing"})
            continue
        result = read_json(result_path)
        selection = result.get("scene_dna_candidate_selection")
        selection = selection if isinstance(selection, dict) else {}
        vnext = selection.get("vnext_selection")
        vnext = vnext if isinstance(vnext, dict) else {}
        attempts = [
            item for item in result.get("reference_attempts", []) if isinstance(item, dict)
        ]
        for attempt in attempts:
            image_path = Path(str(attempt.get("prepared_image_path") or ""))
            if image_path.is_file():
                background_rgb = recorded_alpha_background_rgb(
                    attempt.get("alpha_metadata")
                )
                if background_rgb is None:
                    _, hygiene = clean_chromatic_alpha_edges(Image.open(image_path))
                else:
                    hygiene = audit_sanitized_alpha_edges(
                        Image.open(image_path), background_rgb
                    )
            else:
                hygiene = {"ok": False, "reasons": ["prepared_image_missing"]}
            hygiene_rows.append(
                {
                    "case_id": case_id,
                    "reference_job_id": attempt.get("reference_job_id"),
                    "background": attempt.get("background"),
                    "fixed_neutral_background": attempt.get("background")
                    == "simple solid light gray background",
                    "hygiene_ok": bool(hygiene.get("ok")),
                    "hygiene": hygiene,
                }
            )
        rows.append(
            {
                "case_id": case_id,
                "category": batch.get("category"),
                "status": "completed",
                "candidate_count": len(attempts),
                "current_selector_reference_job_id": selection.get(
                    "combined_selector_reference_job_id"
                ),
                "vnext_selector_reference_job_id": selection.get(
                    "vnext_selector_reference_job_id"
                ),
                "selected_reference_job_id": selection.get(
                    "selected_reference_job_id"
                ),
                "selection_changed": bool(vnext.get("selection_changed")),
                "generability_eligible_candidate_count": vnext.get(
                    "hard_eligible_candidate_count", 0
                ),
                "all_candidates_failed_generability_gate": bool(
                    vnext.get("all_candidates_failed_generability_gate", True)
                ),
                "comparison_available": selection.get(
                    "combined_selector_reference_job_id"
                ) is not None,
                "vnext_rescue_without_current_control": selection.get(
                    "combined_selector_reference_job_id"
                ) is None
                and selection.get("vnext_selector_reference_job_id") is not None,
            }
        )
    completed = [row for row in rows if row.get("status") == "completed"]
    review_ids = {
        str(identifier)
        for row in completed
        for identifier in (
            row.get("current_selector_reference_job_id"),
            row.get("vnext_selector_reference_job_id"),
        )
        if identifier
    }
    for row in hygiene_rows:
        row["review_eligible"] = str(row.get("reference_job_id")) in review_ids
    review_hygiene_rows = [row for row in hygiene_rows if row["review_eligible"]]
    fixed_background_fraction = sum(
        bool(row["fixed_neutral_background"]) for row in hygiene_rows
    ) / max(1, len(hygiene_rows))
    raw_hygiene_fraction = sum(bool(row["hygiene_ok"]) for row in hygiene_rows) / max(
        1, len(hygiene_rows)
    )
    review_hygiene_fraction = sum(
        bool(row["hygiene_ok"]) for row in review_hygiene_rows
    ) / max(
        1, len(review_hygiene_rows)
    )
    change_count = sum(bool(row.get("selection_changed")) for row in completed)
    gates = {
        "all_batches_complete": len(completed) == int(plan.get("batch_count", 0)),
        "fixed_neutral_generation_background_fraction": round(
            fixed_background_fraction, 6
        ),
        "fixed_neutral_generation_background_passed": fixed_background_fraction == 1.0,
        "raw_attempt_alpha_chroma_hygiene_pass_fraction": round(
            raw_hygiene_fraction, 6
        ),
        "raw_attempt_hygiene_rejection_count": sum(
            not row["hygiene_ok"] for row in hygiene_rows
        ),
        "review_eligible_image_count": len(review_hygiene_rows),
        "review_eligible_alpha_chroma_hygiene_pass_fraction": round(
            review_hygiene_fraction, 6
        ),
        "review_eligible_alpha_chroma_hygiene_passed": review_hygiene_fraction
        == 1.0,
        "every_batch_has_generability_eligible_candidate": bool(completed)
        and all(
            int(row.get("generability_eligible_candidate_count", 0) or 0) > 0
            for row in completed
        ),
        "selector_change_count": change_count,
        "selector_nontriviality_passed": change_count > 0,
    }
    passed = bool(
        gates["all_batches_complete"]
        and gates["fixed_neutral_generation_background_passed"]
        and gates["review_eligible_alpha_chroma_hygiene_passed"]
        and gates["every_batch_has_generability_eligible_candidate"]
        and gates["selector_nontriviality_passed"]
    )
    report = {
        "schema": "scene_dna_vnext_engineering_pilot_analysis_v1",
        "plan_path": str(plan_path.resolve()),
        "candidate_root": str(candidate_root.resolve()),
        "engineering_gates_passed": passed,
        "batch_count": int(plan.get("batch_count", 0)),
        "completed_batch_count": len(completed),
        "candidate_image_count": len(hygiene_rows),
        "gates": gates,
        "cases": rows,
        "image_hygiene": hygiene_rows,
        "next_decision": (
            "eligible_to_prepare_new_hidden_human_pilot_not_efficacy_claim"
            if passed
            else "repair_engineering_failures_before_any_new_questionnaire"
        ),
        "limitations": [
            "no new human labels were read or produced",
            "selection changes are behavior, not evidence of preference improvement",
            "3D non-regression remains required after a held-out 2D preference pass",
        ],
    }
    write_json(output_path, report)
    return report


def rescore_vnext_pilot(
    plan_path: Path,
    source_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Replay vNext evidence without regenerating or overwriting frozen images."""

    plan = read_json(plan_path)
    output_root = output_root.resolve()
    rows: list[dict[str, Any]] = []
    for batch in plan.get("batches", []):
        case_id = str(batch["case_id"])
        source_path = source_root / "cases" / case_id / "candidate_batch_result.json"
        if not source_path.is_file():
            rows.append({"case_id": case_id, "status": "missing"})
            continue
        result = read_json(source_path)
        attempts = [
            item for item in result.get("reference_attempts", []) if isinstance(item, dict)
        ]
        hygiene_semantic_eligible: list[dict[str, Any]] = []
        for attempt in attempts:
            score = attempt.get("scene_dna_candidate_score")
            score = score if isinstance(score, dict) else {}
            image_path = Path(str(attempt.get("prepared_image_path") or ""))
            score["generability"] = assess_2d_generability(
                image_path,
                alpha_metadata=attempt.get("alpha_metadata"),
                semantic_report=score.get("semantic"),
                form_report=score.get("form"),
            )
            attempt["scene_dna_candidate_score"] = score
            alpha_quality = (attempt.get("alpha_metadata") or {}).get(
                "alpha_quality", {}
            )
            white_base = alpha_quality.get("white_base_artifact", {})
            semantic = score.get("semantic") or {}
            if (
                bool(attempt.get("alpha_quality_ok"))
                and bool(white_base.get("ok", True))
                and bool(semantic.get("gate_passed"))
            ):
                hygiene_semantic_eligible.append(attempt)
        selection = result.get("scene_dna_candidate_selection")
        selection = selection if isinstance(selection, dict) else {}
        if not hygiene_semantic_eligible:
            rows.append({"case_id": case_id, "status": "no_eligible_candidate"})
            continue
        selected, vnext = select_vnext_candidate(hygiene_semantic_eligible)
        if vnext["all_candidates_failed_generability_gate"]:
            rows.append({"case_id": case_id, "status": "generability_rejected"})
            continue
        current_id = selection.get("combined_selector_reference_job_id")
        selected_id = selected.get("reference_job_id")
        vnext["current_selector_reference_job_id"] = current_id
        vnext["selection_changed"] = bool(current_id and current_id != selected_id)
        vnext["vnext_rescue_without_current_control"] = current_id is None
        selection["vnext_selector_reference_job_id"] = selected_id
        selection["selected_reference_job_id"] = selected_id
        selection["vnext_selection"] = vnext
        promoted = [selected_id] + [
            identifier
            for identifier in selection.get("promoted_reference_job_ids", [])
            if identifier != selected_id
        ]
        maximum = int(selection.get("max_candidates_promoted_to_trellis2", 2) or 2)
        selection["promoted_reference_job_ids"] = promoted[:maximum]
        selection["promoted_reference_image_paths"] = [
            next(
                str(item.get("prepared_image_path"))
                for item in attempts
                if item.get("reference_job_id") == identifier
            )
            for identifier in selection["promoted_reference_job_ids"]
        ]
        result["selected_reference_job_id"] = selected_id
        result["reference_image_path"] = str(selected.get("prepared_image_path"))
        result["scene_dna_candidate_selection"] = selection
        destination = output_root / "cases" / case_id / "candidate_batch_result.json"
        write_json(destination, result)
        rows.append(
            {
                "case_id": case_id,
                "category": batch.get("category"),
                "status": "rescored",
                "current_selector_reference_job_id": current_id,
                "vnext_selector_reference_job_id": selected_id,
                "selection_changed": bool(vnext["selection_changed"]),
                "vnext_rescue_without_current_control": bool(
                    vnext["vnext_rescue_without_current_control"]
                ),
            }
        )
    report = {
        "schema": "scene_dna_vnext_pilot_rescore_v1",
        "plan_path": str(plan_path.resolve()),
        "source_root": str(source_root.resolve()),
        "output_root": str(output_root),
        "source_images_modified": False,
        "rescored_case_count": sum(row.get("status") == "rescored" for row in rows),
        "selection_changed_count": sum(bool(row.get("selection_changed")) for row in rows),
        "rescue_without_current_control_count": sum(
            bool(row.get("vnext_rescue_without_current_control")) for row in rows
        ),
        "cases": rows,
        "limitations": "development replay on the same fresh engineering images; not new efficacy evidence",
    }
    write_json(output_root / "rescore_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--output-dir", required=True, type=Path)
    plan_parser.add_argument("--base-seed", type=int, default=2026082607)
    plan_parser.add_argument("--candidate-count", type=int, default=4)
    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("--plan", required=True, type=Path)
    analyze_parser.add_argument("--candidate-root", required=True, type=Path)
    analyze_parser.add_argument("--output", required=True, type=Path)
    rescore_parser = subparsers.add_parser("rescore")
    rescore_parser.add_argument("--plan", required=True, type=Path)
    rescore_parser.add_argument("--source-root", required=True, type=Path)
    rescore_parser.add_argument("--output-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        report = build_vnext_pilot_plan(
            args.output_dir,
            base_seed=args.base_seed,
            candidate_count=args.candidate_count,
        )
    elif args.command == "analyze":
        report = analyze_vnext_pilot(args.plan, args.candidate_root, args.output)
    else:
        report = rescore_vnext_pilot(
            args.plan, args.source_root, args.output_root
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
