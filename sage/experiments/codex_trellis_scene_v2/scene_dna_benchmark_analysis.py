from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .io_utils import read_json, write_json


def _empty_metrics() -> dict[str, Any]:
    return {
        "batch_count": 0,
        "successful_batch_count": 0,
        "rejected_or_failed_batch_count": 0,
        "selection_changed_count": 0,
        "top2_batch_count": 0,
        "candidate_count": 0,
        "alpha_gate_pass_count": 0,
        "form_gate_pass_count": 0,
        "semantic_gate_pass_count": 0,
        "joint_eligible_count": 0,
    }


def _finalize(metrics: dict[str, Any]) -> dict[str, Any]:
    result = dict(metrics)
    batches = max(1, int(metrics["batch_count"]))
    successful = max(1, int(metrics["successful_batch_count"]))
    candidates = max(1, int(metrics["candidate_count"]))
    result.update(
        {
            "hard_batch_failure_rate": round(
                float(metrics["rejected_or_failed_batch_count"]) / batches, 6
            ),
            "selection_change_rate_among_successful": round(
                float(metrics["selection_changed_count"]) / successful, 6
            ),
            "top2_rate_among_successful": round(
                float(metrics["top2_batch_count"]) / successful, 6
            ),
            "alpha_candidate_pass_rate": round(
                float(metrics["alpha_gate_pass_count"]) / candidates, 6
            ),
            "form_candidate_pass_rate": round(
                float(metrics["form_gate_pass_count"]) / candidates, 6
            ),
            "semantic_candidate_pass_rate": round(
                float(metrics["semantic_gate_pass_count"]) / candidates, 6
            ),
            "joint_candidate_eligibility_rate": round(
                float(metrics["joint_eligible_count"]) / candidates, 6
            ),
        }
    )
    return result


def analyze_candidate_benchmark(summary_path: Path, output_path: Path) -> dict[str, Any]:
    summary = read_json(summary_path)
    global_metrics = _empty_metrics()
    grouped: dict[str, dict[str, dict[str, Any]]] = {
        "category": defaultdict(_empty_metrics),
        "style_condition": defaultdict(_empty_metrics),
        "shape_profile": defaultdict(_empty_metrics),
    }
    failed_cases: list[dict[str, Any]] = []

    for row in summary.get("results", []):
        dimensions = {
            "category": str(row.get("category") or "unknown"),
            "style_condition": str(row.get("style_condition") or "unknown"),
            "shape_profile": str(row.get("shape_profile") or "unknown"),
        }
        targets = [global_metrics] + [
            grouped[name][value] for name, value in dimensions.items()
        ]
        for target in targets:
            target["batch_count"] += 1

        if row.get("status") == "batch_rejected_or_failed":
            for target in targets:
                target["rejected_or_failed_batch_count"] += 1
            failed_cases.append(
                {
                    "case_id": row.get("case_id"),
                    **dimensions,
                    "batch_seed": row.get("batch_seed"),
                    "error": row.get("error"),
                }
            )
            continue

        for target in targets:
            target["successful_batch_count"] += 1
            target["selection_changed_count"] += int(
                bool(row.get("selection_changed"))
            )
            target["top2_batch_count"] += int(
                len(row.get("promoted_reference_job_ids", [])) >= 2
            )

        result_path = Path(str(row.get("candidate_result_path") or ""))
        if not result_path.is_file():
            continue
        batch_result = read_json(result_path)
        selection = batch_result.get("scene_dna_candidate_selection")
        selection = selection if isinstance(selection, dict) else {}
        ranking = [
            item for item in selection.get("ranking", []) if isinstance(item, dict)
        ]
        for item in ranking:
            score = item.get("score")
            score = score if isinstance(score, dict) else {}
            alpha_pass = bool(item.get("alpha_quality_ok"))
            form_pass = bool((score.get("form") or {}).get("gate_passed"))
            semantic_pass = bool((score.get("semantic") or {}).get("gate_passed"))
            joint_pass = bool(item.get("eligible"))
            for target in targets:
                target["candidate_count"] += 1
                target["alpha_gate_pass_count"] += int(alpha_pass)
                target["form_gate_pass_count"] += int(form_pass)
                target["semantic_gate_pass_count"] += int(semantic_pass)
                target["joint_eligible_count"] += int(joint_pass)

    report = {
        "schema": "scene_dna_candidate_benchmark_analysis_v1",
        "source_summary": str(summary_path.resolve()),
        "global": _finalize(global_metrics),
        "by_category": {
            key: _finalize(value)
            for key, value in sorted(grouped["category"].items())
        },
        "by_style_condition": {
            key: _finalize(value)
            for key, value in sorted(grouped["style_condition"].items())
        },
        "by_shape_profile": {
            key: _finalize(value)
            for key, value in sorted(grouped["shape_profile"].items())
        },
        "failed_cases": failed_cases,
        "interpretation_limits": [
            "selection changes and model gate rates are not visual-quality improvements",
            "hidden-label human semantic/form preference remains the primary efficacy endpoint",
            "3D follow-up should stratify changed, unchanged, uncertain, and failed batches",
        ],
    }
    write_json(output_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = analyze_candidate_benchmark(args.summary, args.output)
    print(json.dumps(report["global"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
