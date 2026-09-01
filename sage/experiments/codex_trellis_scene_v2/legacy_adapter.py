"""Compatibility-only adapters from historical entry points to Scene V2."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .cli import build_parser
from .core_domain import SceneRequest
from .pipeline import run_pipeline


FLOW_IDS = ("flow2_image", "flow2_text", "selfmade_text")


def _parser(flow_id: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=flow_id,
        description="Legacy compatibility adapter; execution is owned by Scene V2.",
    )
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--prompt-preset")
    parser.add_argument("--flux-image", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--room-type")
    parser.add_argument("--model")
    parser.add_argument("--asset-strategy", choices=("generate_from_scratch", "asset_library"))
    parser.add_argument("--asset-pipeline")
    parser.add_argument("--asset-source-image-dir")
    parser.add_argument("--trellis-asset-library-dir")
    parser.add_argument("--reuse-asset-dir")
    parser.add_argument("--reuse-asset-alias-file")
    parser.add_argument("--articulated-asset-library-dir")
    parser.add_argument("--human-constraints-file", action="append")
    parser.add_argument("--candidate-count")
    parser.add_argument("--style")
    parser.add_argument("--trellis-url")
    parser.add_argument("--trellis-pipeline-type")
    parser.add_argument("--texture-size")
    parser.add_argument("--decimation-target")
    parser.add_argument("--asset-timeout")
    parser.add_argument("--steps")
    parser.add_argument("--seed")
    parser.add_argument("--blender-bin")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--resume", action="store_true")
    # Accepted historical presentation/front-end switches. They cannot select
    # another relation, layout, assembly, or acceptance implementation.
    for flag in (
        "asset-source-image-required", "asset-source-image-qa-strict",
        "asset-style-consistency", "asset-style-qa-strict", "room-texture-search",
        "layout-critic", "assemble-scene", "trellis-preprocess-image",
        "copy-reused-assets", "partial-reuse-assets", "layout-template-context",
        "final-visual-critic-agent",
    ):
        parser.add_argument(f"--{flag}", action=argparse.BooleanOptionalAction)
    parser.add_argument("--final-visual-critic-max-iterations")
    parser.add_argument("--final-visual-critic-accept-score")
    return parser


def adapt_legacy_args(flow_id: str, argv: Sequence[str]) -> argparse.Namespace:
    if flow_id not in FLOW_IDS:
        raise ValueError(f"unknown legacy flow: {flow_id}")
    old = _parser(flow_id).parse_args(list(argv))
    prompt = (old.prompt or "").strip()
    if old.prompt_file:
        prompt = old.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt and old.prompt_preset:
        prompt = f"Generate the {old.prompt_preset.replace('_', ' ')} scene."
    if not prompt:
        if flow_id == "flow2_image":
            prompt = "Reconstruct a coherent furnished room from the reference image."
        else:
            raise ValueError("--prompt or --prompt-file is required")

    source = "image_reference" if flow_id == "flow2_image" else "text"
    if source == "image_reference" and old.flux_image is None:
        raise ValueError("--flux-image is required by the image front end")
    strategy = old.asset_strategy or "generate_from_scratch"
    asset_mode = "reuse" if strategy == "asset_library" else ("plan" if old.plan_only else "trellis2")
    profile = "plan" if old.plan_only else "development"
    request = SceneRequest.create(
        prompt=prompt,
        output_dir=old.output_dir,
        source=source,
        room_type=old.room_type,
        profile=profile,
        asset_mode=asset_mode,
        reference_image=old.flux_image,
        adapter=f"legacy:{flow_id}",
        compatibility_notes=(
            "legacy front end only; assets, relations, layout, assembly and acceptance are Scene V2 owned",
        ),
    )
    v2_argv = [
        "--prompt", prompt,
        "--output-dir", str(old.output_dir),
        "--profile", profile,
        "--asset-mode", asset_mode,
    ]
    if old.room_type:
        v2_argv += ["--room-type", old.room_type]
    for name in ("model", "trellis_url", "trellis_pipeline_type", "texture_size", "decimation_target", "asset_timeout", "steps", "seed", "blender_bin"):
        value = getattr(old, name)
        if value is not None:
            v2_argv += ["--" + name.replace("_", "-"), str(value)]
    library = old.trellis_asset_library_dir or old.reuse_asset_dir
    if library:
        v2_argv += ["--asset-library-manifest", str(library)]
    if old.plan_only:
        v2_argv += ["--no-assemble", "--no-scene-render-acceptance"]
    else:
        v2_argv += ["--assemble"]
    if old.overwrite:
        v2_argv.append("--overwrite")
    if old.resume:
        v2_argv.append("--resume")
    args = build_parser().parse_args(v2_argv)
    args.scene_request = request
    return args


def run_legacy_cli_adapter(flow_id: str, argv: Sequence[str]) -> dict:
    return run_pipeline(adapt_legacy_args(flow_id, argv))
