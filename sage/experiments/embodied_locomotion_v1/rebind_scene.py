"""Make a new scene revision from unchanged generated inputs, never overwrite."""

import argparse
from pathlib import Path
from .scene import build


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(exist_ok=False)
    for name in ("generator", "GENERATION.json"):
        (a.output / name).symlink_to(
            (a.source / name).resolve(), target_is_directory=name == "generator"
        )
    build(a.output)
