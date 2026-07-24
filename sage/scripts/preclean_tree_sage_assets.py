#!/usr/bin/env python3
"""Pre-clean TreeSAGE assets as a resumable standalone preprocessing step."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from tree_sage_flow2.io import write_json
from run_tree_sage_scene import repair_tree_sage_assets_for_scene


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean a scene's GLB assets outside the monolithic Flow2 run."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--asset-cleanup-worker-timeout", type=float, default=1800.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=512)
    parser.add_argument("--decimation-target", type=int, default=500000)
    parser.add_argument("--trellis-pipeline-type", default="512")
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--asset-source-image-dir", type=Path)
    parser.add_argument("--asset-source-image-required", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--asset-source-image-qa-strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seed", type=int, default=1700)
    parser.add_argument("--force-clean-assets", action="store_true")
    parser.add_argument("--regenerate-integrated-artifacts", action=argparse.BooleanOptionalAction, default=False)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or (args.output_dir.parent / "asset_cleanup_report.json")

    cleanup_args = SimpleNamespace(
        asset_cleanup_subprocess=True,
        asset_cleanup_worker_timeout=args.asset_cleanup_worker_timeout,
        trellis_url=args.trellis_url,
        asset_timeout=args.asset_timeout,
        steps=args.steps,
        texture_size=args.texture_size,
        decimation_target=args.decimation_target,
        trellis_pipeline_type=args.trellis_pipeline_type,
        trellis_preprocess_image=args.trellis_preprocess_image,
        asset_source_image_dir=args.asset_source_image_dir,
        asset_source_image_required=args.asset_source_image_required,
        asset_source_image_qa_strict=args.asset_source_image_qa_strict,
        seed=args.seed,
    )
    reports = repair_tree_sage_assets_for_scene(
        cleanup_args,
        plan,
        args.source_dir,
        args.output_dir,
        force_clean=args.force_clean_assets,
        regenerate_integrated=args.regenerate_integrated_artifacts,
    )
    summary = {
        "schema": "tree_sage_asset_preclean_report_v1",
        "plan": str(args.plan),
        "source_dir": str(args.source_dir),
        "output_dir": str(args.output_dir),
        "object_count": len(plan.get("objects", [])),
        "cleaned_glb_count": len(list(args.output_dir.glob("*.glb"))),
        "worker_subprocess": True,
        "regenerate_integrated_artifacts": bool(args.regenerate_integrated_artifacts),
        "reports": reports,
        "ok": len(list(args.output_dir.glob("*.glb"))) == len(plan.get("objects", [])),
    }
    write_json(report_path, summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
