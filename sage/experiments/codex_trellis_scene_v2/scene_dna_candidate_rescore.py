from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json
from .scene_dna_semantic import (
    DinoV3PrototypeScorer,
    Siglip2SemanticScorer,
    combine_semantic_form_style_scores,
    score_form_contract,
    selection_uncertainty,
)


def _legacy_score(attempt: dict[str, Any]) -> float:
    report = attempt.get("scene_dna_candidate_score")
    report = report if isinstance(report, dict) else {}
    return float(report.get("legacy_pixel_score", report.get("score", 0.0)) or 0.0)


def _candidate_image(
    source_dir: Path,
    case_id: str,
    attempt: dict[str, Any],
) -> Path:
    copied = source_dir / "cases" / case_id / f"candidate_{int(attempt.get('attempt', 0)):02d}.png"
    if copied.is_file():
        return copied.resolve()
    prepared = Path(str(attempt.get("prepared_image_path") or ""))
    if prepared.is_file():
        return prepared.resolve()
    raise FileNotFoundError(f"missing candidate image for {case_id} attempt {attempt.get('attempt')}")


def rescore_existing_candidates(
    plan_path: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    siglip_model: str,
    dino_model: str,
    anchor_manifest_path: Path,
    device: str = "cuda",
    uncertainty_margin: float = 0.03,
) -> dict[str, Any]:
    """Re-score frozen candidate images without regenerating them.

    Model passes are deliberately staged so SigLIP2 and DINOv3 do not occupy
    accelerator memory at the same time.
    """

    plan = read_json(plan_path)
    batches = {
        str(row.get("case_id") or ""): row
        for row in plan.get("batches", [])
        if isinstance(row, dict)
    }
    batches_by_controls = {
        (
            str(row.get("category") or ""),
            str(row.get("style_condition") or ""),
            int(row.get("batch_seed", 0)),
        ): row
        for row in plan.get("batches", [])
        if isinstance(row, dict)
    }
    source_summary = read_json(source_dir / "candidate_benchmark_results.json")
    cases: list[dict[str, Any]] = []
    for source_row in source_summary.get("results", []):
        source_case_id = str(source_row.get("case_id") or "")
        batch = batches.get(source_case_id)
        if batch is None:
            batch = batches_by_controls.get(
                (
                    str(source_row.get("category") or ""),
                    str(source_row.get("style_condition") or ""),
                    int(source_row.get("batch_seed", 0)),
                )
            )
        if batch is None:
            continue
        case_id = str(batch.get("case_id") or source_case_id)
        batch_result = read_json(
            source_dir / "cases" / source_case_id / "candidate_batch_result.json"
        )
        attempts = [
            item
            for item in batch_result.get("reference_attempts", [])
            if isinstance(item, dict)
        ]
        candidates = [
            {
                "reference_job_id": str(item.get("reference_job_id") or ""),
                "attempt": int(item.get("attempt", 0)),
                "image_path": str(_candidate_image(source_dir, source_case_id, item)),
                "legacy_pixel_score": _legacy_score(item),
                "alpha_quality_ok": bool(item.get("alpha_quality_ok", False)),
            }
            for item in attempts
        ]
        cases.append(
            {
                "case_id": case_id,
                "source_case_id": source_case_id,
                "batch": batch,
                "candidates": candidates,
            }
        )

    semantic_scorer = Siglip2SemanticScorer(siglip_model, device=device)
    try:
        for case in cases:
            contract = case["batch"]["semantic_form_contract"]
            for candidate in case["candidates"]:
                path = Path(candidate["image_path"])
                candidate["form"] = score_form_contract(path, contract)
                candidate["semantic"] = semantic_scorer.score(path, contract)
    finally:
        semantic_scorer.close()

    anchor_manifest = read_json(anchor_manifest_path)
    dino_scorer = DinoV3PrototypeScorer(
        dino_model,
        anchor_manifest,
        device=device,
    )
    try:
        for case in cases:
            contract = case["batch"]["semantic_form_contract"]
            for candidate in case["candidates"]:
                candidate["anchor_similarity"] = dino_scorer.score(
                    Path(candidate["image_path"]), contract
                )
    finally:
        dino_scorer.close()

    results: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for case in cases:
        batch = case["batch"]
        candidates = case["candidates"]
        for candidate in candidates:
            anchor = candidate["anchor_similarity"]
            anchor_score = (
                float(anchor["score"])
                if anchor.get("evaluated") and anchor.get("score") is not None
                else None
            )
            candidate["combined"] = combine_semantic_form_style_scores(
                pixel_style_score=float(candidate["legacy_pixel_score"]),
                form_report=candidate["form"],
                semantic_report=candidate["semantic"],
                anchor_similarity_score=anchor_score,
            )
        alpha_eligible = [item for item in candidates if item["alpha_quality_ok"]]
        form_eligible = [
            item for item in alpha_eligible if item["form"].get("gate_passed")
        ]
        semantic_eligible = [
            item for item in form_eligible if item["semantic"].get("gate_passed")
        ]
        failure_reason = None
        if not alpha_eligible:
            failure_reason = "all_candidates_failed_alpha_gate"
        elif not form_eligible:
            failure_reason = "all_candidates_failed_form_gate"
        elif not semantic_eligible:
            failure_reason = "all_candidates_failed_semantic_gate"
        legacy = max(candidates, key=lambda item: item["legacy_pixel_score"])
        row: dict[str, Any] = {
            "case_id": case["case_id"],
            "source_case_id": case["source_case_id"],
            "category": batch["category"],
            "style_condition": batch["style_condition"],
            "shape_profile": batch["semantic_form_contract"]["shape_profile"],
            "batch_seed": batch["batch_seed"],
            "legacy_selected_reference_job_id": legacy["reference_job_id"],
            "legacy_selected_score": legacy["legacy_pixel_score"],
            "candidate_count": len(candidates),
            "alpha_eligible_count": len(alpha_eligible),
            "form_eligible_count": len(form_eligible),
            "semantic_eligible_count": len(semantic_eligible),
            "failure_reason": failure_reason,
            "candidates": candidates,
        }
        if failure_reason is None:
            ranking = sorted(
                semantic_eligible,
                key=lambda item: float(item["combined"]["score"]),
                reverse=True,
            )
            semantic_best = max(
                semantic_eligible,
                key=lambda item: float(item["semantic"]["score"]),
            )
            form_best = max(
                semantic_eligible,
                key=lambda item: float(item["form"]["score"]),
            )
            uncertainty = selection_uncertainty(
                [float(item["combined"]["score"]) for item in ranking],
                margin_threshold=uncertainty_margin,
                scorer_conflict=semantic_best is not form_best,
            )
            promotion_count = min(
                2,
                len(ranking),
                int(uncertainty["recommended_promotion_count"]),
            )
            selected = ranking[0]
            row.update(
                {
                    "status": "selected",
                    "proposed_selected_reference_job_id": selected["reference_job_id"],
                    "proposed_selected_score": selected["combined"]["score"],
                    "selection_changed": selected["reference_job_id"]
                    != legacy["reference_job_id"],
                    "uncertainty": uncertainty,
                    "promoted_reference_job_ids": [
                        item["reference_job_id"] for item in ranking[:promotion_count]
                    ],
                }
            )
            if row["selection_changed"]:
                comparisons.append(
                    {
                        "case_id": case["case_id"],
                        "category": batch["category"],
                        "shape_profile": batch["semantic_form_contract"]["shape_profile"],
                        "object_requirement": batch["object_prompt"],
                        "style_requirement": batch["style_condition"],
                        "baseline": {
                            "asset_id": legacy["reference_job_id"],
                            "image_path": legacy["image_path"],
                        },
                        "proposed": {
                            "asset_id": selected["reference_job_id"],
                            "image_path": selected["image_path"],
                        },
                    }
                )
        else:
            row.update(
                {
                    "status": "batch_rejected",
                    "selection_changed": False,
                    "promoted_reference_job_ids": [],
                    "uncertainty": None,
                }
            )
        results.append(row)
        print(
            f"[{len(results)}/{len(cases)}] {case['case_id']} "
            f"status={row['status']} semantic_eligible={len(semantic_eligible)}",
            flush=True,
        )

    selected_rows = [item for item in results if item["status"] == "selected"]
    report = {
        "schema": "scene_dna_candidate_rescore_v1",
        "plan_path": str(plan_path.resolve()),
        "source_dir": str(source_dir.resolve()),
        "completed_batch_count": len(results),
        "selected_batch_count": len(selected_rows),
        "rejected_batch_count": len(results) - len(selected_rows),
        "selection_changed_count": sum(
            bool(item["selection_changed"]) for item in selected_rows
        ),
        "uncertain_top2_count": sum(
            len(item["promoted_reference_job_ids"]) == 2 for item in selected_rows
        ),
        "results": results,
        "limitations": [
            "reuses a frozen candidate set and does not measure generation-time failure changes",
            "human blind labels remain required before threshold promotion",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "candidate_rescore_results.json", report)
    write_json(
        output_dir / "blind_comparisons.json",
        {"schema": "scene_dna_blind_comparisons_v1", "comparisons": comparisons},
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--siglip-model", required=True)
    parser.add_argument("--dino-model", required=True)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--uncertainty-margin", type=float, default=0.03)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = rescore_existing_candidates(
        args.plan,
        args.source_dir,
        args.output_dir,
        siglip_model=str(args.siglip_model),
        dino_model=str(args.dino_model),
        anchor_manifest_path=args.anchor_manifest,
        device=str(args.device),
        uncertainty_margin=float(args.uncertainty_margin),
    )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "completed_batch_count",
                    "selected_batch_count",
                    "rejected_batch_count",
                    "selection_changed_count",
                    "uncertain_top2_count",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
