"""Invoke the unmodified public generator on a frozen local-only request."""

import argparse
import json
import os
import time
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.cli import build_parser
from sage.experiments.codex_trellis_scene_v2.pipeline import run_pipeline
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    write_json_atomic,
)


def generate(scene):
    if (scene / "GENERATION.json").exists():
        raise FileExistsError(scene)
    for kind in ("CONFIG", "CACHE", "DATA"):
        directory = scene / f"xdg_{kind.lower()}"
        directory.mkdir(exist_ok=False)
        os.environ[f"XDG_{kind}_HOME"] = str(directory)
    os.environ["SAGE_BLENDER_TIMEOUT"] = "300"
    began = time.monotonic()
    summary = run_pipeline(
        build_parser().parse_args(json.loads((scene / "CLI.json").read_text()))
    )
    write_json_atomic(
        scene / "GENERATION.json",
        {
            "schema": "locomotion-generator-result/v1",
            "summary": summary,
            "wall_seconds": time.monotonic() - began,
            "physics_steps": 0,
            "public_cli": json.loads((scene / "CLI.json").read_text()),
        },
    )
    print("generated", scene)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scene", type=Path, required=True)
    generate(p.parse_args().scene)
