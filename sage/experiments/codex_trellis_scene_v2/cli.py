from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .pipeline import run_pipeline
from .policies import FLOOR_MATERIAL_PRESETS, WALL_MATERIAL_PRESETS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Isolated V2: prompt expansion -> architecture -> reuse/TRELLIS.2 -> constrained layout -> repair."
    )
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--room-type", choices=("bedroom", "living_room", "kitchen", "study", "restroom"))
    parser.add_argument(
        "--floor-material",
        choices=tuple(sorted(FLOOR_MATERIAL_PRESETS)),
        help="Override the room policy's generated floor material preset.",
    )
    parser.add_argument(
        "--wall-material",
        choices=tuple(sorted(WALL_MATERIAL_PRESETS)),
        help="Override the room policy's default generated wall finish.",
    )
    parser.add_argument(
        "--accent-wall",
        choices=("north", "south", "east", "west"),
        help="Apply one per-wall material override; requires --accent-wall-material.",
    )
    parser.add_argument(
        "--accent-wall-material",
        choices=tuple(sorted(WALL_MATERIAL_PRESETS)),
        help="Material for --accent-wall; both options must be provided together.",
    )
    parser.add_argument(
        "--window-wall",
        choices=("north", "south", "east", "west"),
        help="Explicitly place the main window; this may override the different-wall soft rule.",
    )
    parser.add_argument("--model", default=os.environ.get("SAGE_CODEX_MODEL", "gpt-5.6-sol"))
    parser.add_argument("--expander", choices=("rules", "hybrid", "codex"), default="hybrid")
    parser.add_argument("--planner", choices=("rules", "codex"), default="codex")
    parser.add_argument("--codex-repair", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--repair-iterations", type=int, default=2)
    parser.add_argument("--allow-invalid", action="store_true")
    parser.add_argument(
        "--hard-min-scene-objects",
        type=int,
        help="Override the room policy's hard object-count minimum.",
    )
    parser.add_argument(
        "--target-max-scene-objects",
        "--soft-max-scene-objects",
        dest="target_max_scene_objects",
        type=int,
        help="Automatic-expansion target; explicit and room-required instances may exceed it.",
    )
    parser.add_argument(
        "--max-auto-inferred-assets",
        "--max-optional-assets",
        dest="max_auto_inferred_assets",
        type=int,
        help="Limit only Codex-inferred optional objects, never explicit prompt instances.",
    )

    parser.add_argument("--asset-mode", choices=("plan", "reuse", "trellis2"), default="plan")
    parser.add_argument("--asset-library-manifest", type=Path)
    parser.add_argument("--max-new-assets", type=int, default=8)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument(
        "--trellis-pipeline-type",
        choices=("512", "1024", "1024_cascade", "1536_cascade"),
        default="512",
    )
    parser.add_argument("--trellis-preprocess-image", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seed", type=int, default=2400)
    parser.add_argument("--asset-timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--decimation-target", type=int, default=500000)

    parser.add_argument("--assemble", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--render-preview",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render front-left and front-center downward-45-degree PNGs whenever Blender assembles a GLB.",
    )
    parser.add_argument("--blender-bin", default="/data/wsj/tools/blender/blender")
    parser.add_argument("--mujoco-check", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--mujoco-python",
        default=os.environ.get(
            "SAGE_CODEX_MUJOCO_PYTHON",
            "/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python",
        ),
    )
    return parser


def main() -> None:
    summary = run_pipeline(build_parser().parse_args())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
