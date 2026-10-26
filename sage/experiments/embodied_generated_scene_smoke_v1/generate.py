"""Run the public SAGE scene generator for the frozen one-shot request."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable

from sage.experiments.codex_trellis_scene_v2.cli import build_parser
from sage.experiments.codex_trellis_scene_v2.pipeline import run_pipeline

from .common import RUN_ROOT, write_json


def main(argv: Iterable[str] | None = None) -> int:
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    cli = json.loads((args.run_root / "generator_request/CLI.json").read_text())
    work = args.run_root / "generator_work"
    work.mkdir(exist_ok=False)
    for kind in ("CONFIG", "CACHE", "DATA"):
        directory = work / f"xdg_{kind.lower()}"
        directory.mkdir()
        os.environ[f"XDG_{kind}_HOME"] = str(directory)
    os.environ["SAGE_BLENDER_TIMEOUT"] = "300"
    summary = run_pipeline(build_parser().parse_args(cli))
    report = {
        "schema": "embodied-generated-scene-generator-result/v1",
        "generated": True,
        "public_cli": cli,
        "summary": summary,
        "physics_steps": 0,
        "render_passes": 0,
        "production_accepted": False,
    }
    write_json(args.run_root / "GENERATOR_RESULT.json", report)
    print(json.dumps(report, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
