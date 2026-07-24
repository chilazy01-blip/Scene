#!/usr/bin/env python3
"""Clean one TreeSAGE asset in an isolated process."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from tree_sage_flow2.io import write_json

from run_selfmade_trellis_scene import clean_asset_ground_artifacts
from run_tree_sage_scene import _tree_sage_asset_cleanup_retry_object, generate_tree_sage_asset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean one TreeSAGE GLB asset and write a JSON report.")
    parser.add_argument("--object-json", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--meta-source", type=Path)
    parser.add_argument("--meta-output", type=Path)
    parser.add_argument("--force-clean", action="store_true")
    parser.add_argument("--regenerate-integrated", action="store_true")
    parser.add_argument("--regenerated-raw-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)

    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--decimation-target", type=int, default=500000)
    parser.add_argument("--trellis-pipeline-type", default="512")
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--asset-source-image-dir", type=Path)
    parser.add_argument("--asset-source-image-required", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--asset-source-image-qa-strict", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    obj = json.loads(args.object_json.read_text(encoding="utf-8"))
    report = clean_asset_ground_artifacts(args.source, args.output, obj, force=args.force_clean)
    if report.get("requires_regeneration") and args.regenerate_integrated:
        retry_obj = _tree_sage_asset_cleanup_retry_object(obj)
        regenerated_src = generate_tree_sage_asset(
            args,
            retry_obj,
            args.regenerated_raw_dir,
            seed=args.seed,
            force=True,
        )
        retry_report = clean_asset_ground_artifacts(regenerated_src, args.output, obj, force=True)
        report["regeneration"] = {
            "enabled": True,
            "route": "tree_sage_generate_asset",
            "uses_asset_source_image_dir": bool(args.asset_source_image_dir),
            "retry_asset_prompt": retry_obj["asset_prompt"],
            "raw_regenerated_asset": str(regenerated_src),
            "cleanup_report": retry_report,
        }
        report["artifact_action"] = (
            "regenerated_then_component_cleanup"
            if retry_report.get("changed")
            else "regenerated_still_requires_review"
            if retry_report.get("requires_regeneration")
            else "regenerated"
        )
    if args.meta_source and args.meta_source.exists() and args.meta_output:
        args.meta_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.meta_source, args.meta_output)
    write_json(args.report, report)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[clean-asset-worker:error] {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
