from __future__ import annotations

import argparse
import copy
import json
import shutil
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sage.server.trellis2_flux_bridge_server import Trellis2BridgeRuntime

from .io_utils import read_json, write_json


def build_alpha_runtime(
    output_dir: Path,
    *,
    rmbg_model: str,
    rmbg_module_root: str,
    device: str,
) -> Trellis2BridgeRuntime:
    """Build the bridge's alpha path without loading Flux or TRELLIS."""

    args = Namespace(
        output_dir=str((output_dir / "alpha_runtime").resolve()),
        device=device,
        alpha_mode="rembg",
        rmbg_model=rmbg_model,
        rmbg_module_root=rmbg_module_root,
        rmbg_offload_cpu=True,
        alpha_bbox_threshold=24,
        alpha_content_scale=0.86,
        alpha_quality_check=True,
        alpha_require_quality=False,
        alpha_min_foreground_ratio=0.012,
        alpha_max_foreground_ratio=0.68,
        alpha_max_border_foreground_ratio=0.015,
        white_base_quality_check=True,
        white_base_require_clean=True,
        white_base_auto_repair=True,
        scene_dna_form_scoring=False,
        scene_dna_semantic_scoring="off",
        scene_dna_anchor_manifest=None,
    )
    return Trellis2BridgeRuntime(args)


def _successful_source_rows(source_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    summary = read_json(source_dir / "candidate_benchmark_results.json")
    successful: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in summary.get("results", []):
        if not isinstance(row, dict):
            continue
        case_id = str(row.get("case_id") or "")
        result_path = source_dir / "cases" / case_id / "candidate_batch_result.json"
        if result_path.is_file():
            successful.append(row)
        else:
            skipped.append(
                {
                    "case_id": case_id,
                    "status": str(row.get("status") or "missing_batch_result"),
                    "error": row.get("error"),
                }
            )
    return summary, successful, skipped


def reprocess_existing_candidates(
    plan_path: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    runtime: Trellis2BridgeRuntime,
    resume: bool = True,
    case_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Re-run RMBG and safe alpha cleanup on preserved raw candidate renders."""

    plan = read_json(plan_path)
    batches = {
        str(row.get("case_id") or ""): row
        for row in plan.get("batches", [])
        if isinstance(row, dict)
    }
    source_summary, source_rows, skipped = _successful_source_rows(source_dir)
    if case_ids:
        source_rows = [
            row for row in source_rows if str(row.get("case_id") or "") in case_ids
        ]
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    fake_pipeline = SimpleNamespace(_rembg_args={})

    for case_number, source_row in enumerate(source_rows, start=1):
        case_id = str(source_row.get("case_id") or "")
        batch = batches.get(case_id)
        if batch is None:
            raise KeyError(f"case {case_id} is missing from {plan_path}")
        source_result_path = (
            source_dir / "cases" / case_id / "candidate_batch_result.json"
        )
        case_dir = output_dir / "cases" / case_id
        output_result_path = case_dir / "candidate_batch_result.json"
        if resume and output_result_path.is_file():
            processed_rows.append(
                {
                    **source_row,
                    "candidate_result_path": str(output_result_path),
                    "alpha_reprocess_status": "resumed",
                }
            )
            existing = read_json(output_result_path)
            for attempt in existing.get("reference_attempts", []):
                metadata = attempt.get("alpha_metadata", {})
                repair = metadata.get("white_base_repair", {})
                audit_rows.append(
                    {
                        "case_id": case_id,
                        "attempt": int(attempt.get("attempt", 0)),
                        "reference_job_id": str(attempt.get("reference_job_id") or ""),
                        "alpha_quality_ok": bool(attempt.get("alpha_quality_ok")),
                        "repair_applied": bool(repair.get("applied")),
                        "repair_rolled_back": bool(repair.get("rolled_back")),
                        "protected_connected_region_count": sum(
                            row.get("decision") == "protected_connected_subject_region"
                            for row in metadata.get("alpha_quality", {})
                            .get("white_base_artifact", {})
                            .get("candidates", [])
                            if isinstance(row, dict)
                        ),
                    }
                )
            print(f"[{case_number}/{len(source_rows)}] {case_id} resumed", flush=True)
            continue

        source_result = read_json(source_result_path)
        updated_result = copy.deepcopy(source_result)
        updated_attempts: list[dict[str, Any]] = []
        case_dir.mkdir(parents=True, exist_ok=True)
        scene_dna = {
            "global_tags": str(batch.get("style_condition") or "").split("_"),
            "individuality_tags": [],
            "semantic_form_contract": batch.get("semantic_form_contract", {}),
        }
        for attempt in source_result.get("reference_attempts", []):
            if not isinstance(attempt, dict):
                continue
            updated = copy.deepcopy(attempt)
            attempt_index = int(attempt.get("attempt", 0))
            reference_job_id = str(attempt.get("reference_job_id") or "")
            raw_path = Path(str(attempt.get("source_image_path") or ""))
            if not raw_path.is_file():
                raise FileNotFoundError(
                    f"missing preserved raw candidate for {case_id} attempt {attempt_index}: {raw_path}"
                )
            old_metadata = attempt.get("alpha_metadata", {})
            object_text = str(
                old_metadata.get("object_text")
                or batch.get("object_prompt")
                or source_result.get("input_text")
                or ""
            )
            prepared = runtime._prepare_reference_with_rmbg(
                raw_path,
                reference_job_id,
                fake_pipeline,
                object_text=object_text,
            )
            destination = case_dir / f"candidate_{attempt_index:02d}.png"
            shutil.copy2(prepared, destination)
            metadata = runtime._read_alpha_metadata(reference_job_id)
            updated["prepared_image_path"] = str(destination.resolve())
            updated["alpha_metadata"] = metadata
            updated["alpha_quality_ok"] = runtime._alpha_metadata_ok(metadata)
            updated["scene_dna_candidate_score"] = (
                runtime._scene_dna_visual_candidate_score(
                    destination,
                    metadata,
                    scene_dna,
                )
            )
            updated_attempts.append(updated)
            repair = metadata.get("white_base_repair", {})
            audit_rows.append(
                {
                    "case_id": case_id,
                    "attempt": attempt_index,
                    "reference_job_id": reference_job_id,
                    "alpha_quality_ok": bool(updated["alpha_quality_ok"]),
                    "repair_applied": bool(repair.get("applied")),
                    "repair_rolled_back": bool(repair.get("rolled_back")),
                    "protected_connected_region_count": sum(
                        row.get("decision") == "protected_connected_subject_region"
                        for row in metadata.get("alpha_quality", {})
                        .get("white_base_artifact", {})
                        .get("candidates", [])
                        if isinstance(row, dict)
                    ),
                }
            )
        updated_result["reference_attempts"] = updated_attempts
        updated_result["alpha_reprocess"] = {
            "schema": "scene_dna_alpha_reprocess_case_v1",
            "source_result_path": str(source_result_path.resolve()),
            "raw_generation_reused": True,
            "flux_regenerated": False,
            "trellis_regenerated": False,
        }
        write_json(output_result_path, updated_result)
        processed_rows.append(
            {
                **source_row,
                "candidate_result_path": str(output_result_path),
                "alpha_reprocess_status": "processed",
            }
        )
        print(
            f"[{case_number}/{len(source_rows)}] {case_id} "
            f"attempts={len(updated_attempts)}",
            flush=True,
        )

    compatible_summary = {
        **source_summary,
        "schema": "scene_dna_alpha_reprocessed_candidate_benchmark_v1",
        "source_dir": str(source_dir.resolve()),
        "plan_path": str(plan_path.resolve()),
        "completed_batch_count": len(processed_rows),
        "rejected_or_failed_batch_count": len(skipped),
        "results": processed_rows,
        "alpha_reprocess_only": True,
        "raw_generation_reused": True,
    }
    partial_run = bool(case_ids)
    summary_name = (
        "candidate_benchmark_results.partial.json"
        if partial_run
        else "candidate_benchmark_results.json"
    )
    write_json(output_dir / summary_name, compatible_summary)
    report = {
        "schema": "scene_dna_alpha_reprocess_report_v1",
        "plan_path": str(plan_path.resolve()),
        "source_dir": str(source_dir.resolve()),
        "output_dir": str(output_dir),
        "processed_case_count": len(processed_rows),
        "processed_candidate_count": len(audit_rows),
        "partial_case_selection": sorted(case_ids) if case_ids else [],
        "skipped_source_cases": skipped,
        "alpha_quality_pass_count": sum(row["alpha_quality_ok"] for row in audit_rows),
        "repair_applied_count": sum(row["repair_applied"] for row in audit_rows),
        "repair_rollback_count": sum(row["repair_rolled_back"] for row in audit_rows),
        "protected_connected_region_candidate_count": sum(
            int(row["protected_connected_region_count"]) for row in audit_rows
        ),
        "candidates": audit_rows,
        "limitations": [
            "reuses frozen raw Flux images and does not regenerate 2D content",
            "semantic, form, and anchor scores must be recomputed after alpha reprocessing",
        ],
    }
    report_name = (
        "alpha_reprocess_report.partial.json"
        if partial_run
        else "alpha_reprocess_report.json"
    )
    write_json(output_dir / report_name, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--rmbg-model", required=True)
    parser.add_argument("--rmbg-module-root", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--resume", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--case-id", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_alpha_runtime(
        args.output_dir,
        rmbg_model=str(args.rmbg_model),
        rmbg_module_root=str(args.rmbg_module_root),
        device=str(args.device),
    )
    report = reprocess_existing_candidates(
        args.plan,
        args.source_dir,
        args.output_dir,
        runtime=runtime,
        resume=bool(args.resume),
        case_ids={str(case_id) for case_id in args.case_id} or None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
