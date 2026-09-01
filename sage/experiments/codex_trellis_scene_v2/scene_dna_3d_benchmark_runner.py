from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from .assets import generate_trellis_asset
from .brief import build_asset_generation_spec
from .io_utils import read_json, write_json
from .scene_dna import build_scene_dna_contract
from .scene_dna_effectiveness import compare_effectiveness
from .scene_dna_feasibility import assess_3d_feasibility, select_3d_candidate
from .scene_dna_multiview import (
    evaluate_multiview_manifest,
    render_and_evaluate_generated_asset,
    structure_profile_for_object,
)
from .scene_dna_semantic import Siglip2SemanticScorer


def _style_terms(style_requirement: str) -> list[str]:
    return {
        "warm_modern": ["warm", "modern", "clean lines"],
        "cool_industrial": ["cool", "industrial", "clean lines"],
    }.get(style_requirement, [style_requirement.replace("_", " ")])


def run_paired_3d_benchmark(
    comparisons_path: Path,
    benchmark_plan_path: Path,
    output_dir: Path,
    *,
    trellis_url: str,
    blender_bin: Path,
    maximum_cases: int = 4,
    case_ids: set[str] | None = None,
    timeout: float = 1800.0,
    resolution: int = 420,
    steps: int = 12,
    texture_size: int = 1024,
    decimation_target: int = 100_000,
    pipeline_type: str = "1024_cascade",
    refresh_evaluation: bool = False,
    semantic_model: str | None = None,
    semantic_device: str = "cpu",
) -> dict[str, Any]:
    """Generate same-seed baseline/proposed GLBs from a frozen 2D comparison set."""

    comparisons = read_json(comparisons_path).get("comparisons", [])
    if case_ids:
        comparisons = [
            row
            for row in comparisons
            if str(row.get("case_id") or "") in case_ids
        ]
    plan = read_json(benchmark_plan_path)
    batches = {
        str(item.get("case_id") or ""): item
        for item in plan.get("batches", [])
        if isinstance(item, dict)
    }
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    semantic_scorer = (
        Siglip2SemanticScorer(semantic_model, device=semantic_device)
        if semantic_model
        else None
    )
    results: list[dict[str, Any]] = []
    blind_rows: list[dict[str, Any]] = []
    for row in comparisons[: max(0, int(maximum_cases))]:
        case_id = str(row.get("case_id") or "")
        batch = batches.get(case_id)
        if batch is None:
            results.append({"case_id": case_id, "status": "missing_frozen_batch"})
            continue
        category = str(row.get("category") or batch.get("category") or "object")
        dimensions = deepcopy(batch.get("requested_dimensions") or {})
        styles = _style_terms(str(row.get("style_requirement") or ""))
        obj = {
            "id": case_id,
            "category": category,
            "dimensions": dimensions,
            "requested_dimensions": deepcopy(dimensions),
            "asset_prompt": str(row.get("object_requirement") or batch["object_prompt"]),
        }
        obj["asset_generation_spec"] = build_asset_generation_spec(
            obj,
            styles,
            obj["asset_prompt"],
        )
        contract = build_scene_dna_contract(
            {
                "original_prompt": obj["asset_prompt"],
                "styles": styles,
                "objects": [obj],
                "relations": [],
            }
        )
        case_dir = output_dir / case_id
        write_json(case_dir / "scene_dna_contract.json", contract)
        pair_reports: dict[str, dict[str, Any]] = {}
        pair_glbs: dict[str, str] = {}
        try:
            for method in ("baseline", "proposed"):
                asset = row.get(method)
                if not isinstance(asset, dict):
                    raise ValueError(f"{case_id} has no {method} comparison asset")
                reference = Path(str(asset["image_path"])).resolve()
                asset_dir = case_dir / method / "assets"
                glb_path = asset_dir / f"{case_id}.glb"
                metadata_path = case_dir / method / "generation_metadata.json"
                if not glb_path.is_file():
                    metadata = generate_trellis_asset(
                        obj,
                        glb_path,
                        trellis_url=trellis_url,
                        seed=int(batch["batch_seed"]),
                        timeout=timeout,
                        steps=steps,
                        texture_size=texture_size,
                        decimation_target=decimation_target,
                        pipeline_type=pipeline_type,
                        preprocess_image=False,
                        reference_image_path=reference,
                    )
                    write_json(metadata_path, metadata)
                report_path = case_dir / method / "multiview" / "scene_dna_multiview_report.json"
                if report_path.is_file() and refresh_evaluation:
                    manifest_path = report_path.parent / "asset_turntable_manifest.json"
                    multiview = evaluate_multiview_manifest(
                        read_json(manifest_path),
                        contract,
                        object_id=case_id,
                        category=category,
                        reference_image_path=reference,
                        structure_profile=structure_profile_for_object(
                            obj,
                            contract.get("object_profiles", {})
                            .get(case_id, {})
                            .get("semantic_form_contract", {}),
                        ),
                        semantic_scorer=semantic_scorer,
                    )
                    multiview["manifest_path"] = str(manifest_path)
                    multiview["contact_sheet_path"] = str(
                        report_path.parent / "scene_dna_multiview_contact_sheet.png"
                    )
                    write_json(report_path, multiview)
                elif report_path.is_file():
                    multiview = read_json(report_path)
                else:
                    multiview = render_and_evaluate_generated_asset(
                        blender_bin=blender_bin,
                        asset_dir=asset_dir,
                        output_dir=case_dir / method / "multiview",
                        obj=obj,
                        contract=contract,
                        reference_image_path=reference,
                        resolution=resolution,
                        semantic_scorer=semantic_scorer,
                    )
                pair_reports[method] = multiview
                pair_glbs[method] = str(glb_path)
            production_preview_candidates = [
                {
                    "attempt": 0,
                    "candidate_rank": index,
                    "path": pair_glbs[method],
                    "multiview": pair_reports[method],
                    "method": method,
                }
                for index, method in enumerate(("baseline", "proposed"), start=1)
            ]
            selected_preview, production_preview = select_3d_candidate(
                production_preview_candidates,
                require_hard_geometry=True,
            )
            production_preview["selected_method"] = str(
                selected_preview.get("method") or ""
            )
            comparison = compare_effectiveness(
                pair_reports["baseline"], pair_reports["proposed"]
            )
            result = {
                "case_id": case_id,
                "category": category,
                "status": "completed",
                "same_trellis_seed": int(batch["batch_seed"]),
                "only_intended_difference": "selected 2D reference image",
                "glbs": pair_glbs,
                "feasibility": {
                    method: assess_3d_feasibility(pair_reports[method])
                    for method in ("baseline", "proposed")
                },
                "production_selector_preview": production_preview,
                "comparison": comparison,
            }
            results.append(result)
            blind_rows.append(
                {
                    "case_id": case_id,
                    "category": category,
                    "shape_profile": str(row.get("shape_profile") or ""),
                    "object_requirement": obj["asset_prompt"],
                    "style_requirement": str(row.get("style_requirement") or ""),
                    "baseline": {
                        "asset_id": f"{case_id}_baseline_3d",
                        "image_path": str(pair_reports["baseline"]["contact_sheet_path"]),
                    },
                    "proposed": {
                        "asset_id": f"{case_id}_proposed_3d",
                        "image_path": str(pair_reports["proposed"]["contact_sheet_path"]),
                    },
                }
            )
        except Exception as exc:
            results.append(
                {
                    "case_id": case_id,
                    "category": category,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
        write_json(
            output_dir / "paired_3d_benchmark_results.json",
            {
                "schema": "scene_dna_paired_3d_benchmark_v1",
                "controlled_same_seed": True,
                "results": results,
            },
        )
        write_json(
            output_dir / "blind_comparisons_3d.json",
            {"schema": "scene_dna_blind_comparisons_3d_v1", "comparisons": blind_rows},
        )
    completed = sum(item.get("status") == "completed" for item in results)
    report = {
        "schema": "scene_dna_paired_3d_benchmark_v1",
        "controlled_same_seed": True,
        "requested_case_count": min(len(comparisons), int(maximum_cases)),
        "completed_case_count": completed,
        "failed_case_count": len(results) - completed,
        "results": results,
        "limitations": [
            "automated multiview scores do not replace hidden-label human semantic/form review",
            "pilot cases were selected because 2D ranking changed and are not held-out efficacy evidence",
        ],
    }
    write_json(output_dir / "paired_3d_benchmark_results.json", report)
    if semantic_scorer is not None:
        semantic_scorer.close()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparisons", required=True, type=Path)
    parser.add_argument("--benchmark-plan", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--maximum-cases", type=int, default=4)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--resolution", type=int, default=420)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=1024)
    parser.add_argument("--decimation-target", type=int, default=100_000)
    parser.add_argument(
        "--semantic-model",
        help="Optional local SigLIP2 checkpoint for final multi-view category/style scoring.",
    )
    parser.add_argument("--semantic-device", default="cpu")
    parser.add_argument(
        "--refresh-evaluation",
        action="store_true",
        help="re-score existing multiview renders without regenerating GLBs",
    )
    parser.add_argument(
        "--pipeline-type",
        choices=("512", "1024", "1024_cascade", "1536_cascade"),
        default="1024_cascade",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_paired_3d_benchmark(
        args.comparisons,
        args.benchmark_plan,
        args.output_dir,
        trellis_url=str(args.trellis_url),
        blender_bin=args.blender,
        maximum_cases=int(args.maximum_cases),
        case_ids={str(item) for item in args.case_id} or None,
        timeout=float(args.timeout),
        resolution=int(args.resolution),
        steps=int(args.steps),
        texture_size=int(args.texture_size),
        decimation_target=int(args.decimation_target),
        pipeline_type=str(args.pipeline_type),
        refresh_evaluation=bool(args.refresh_evaluation),
        semantic_model=args.semantic_model,
        semantic_device=str(args.semantic_device),
    )
    print(json.dumps({key: report[key] for key in ("requested_case_count", "completed_case_count", "failed_case_count")}, indent=2))
    return 0 if report["failed_case_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
