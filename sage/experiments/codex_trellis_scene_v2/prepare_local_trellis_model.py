from __future__ import annotations

import argparse
import json
from pathlib import Path


def patch_config(source: Path, destination: Path, rembg_model: Path) -> None:
    payload = json.loads(source.read_text(encoding="utf-8"))
    args = payload.get("args") if isinstance(payload, dict) else None
    if not isinstance(args, dict):
        raise ValueError(f"Invalid TRELLIS.2 pipeline config: {source}")
    rembg = args.get("rembg_model")
    if not isinstance(rembg, dict):
        raise ValueError(f"Missing rembg_model in {source}")
    rembg_args = rembg.get("args")
    if not isinstance(rembg_args, dict):
        raise ValueError(f"Missing rembg_model.args in {source}")
    rembg_args["model_name"] = str(rembg_model.resolve())
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a small local TRELLIS.2 model overlay with offline RMBG paths."
    )
    parser.add_argument("--source-model", required=True, type=Path)
    parser.add_argument("--rembg-model", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    source_model = args.source_model.expanduser().resolve()
    rembg_model = args.rembg_model.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not (source_model / "ckpts").is_dir():
        raise FileNotFoundError(f"TRELLIS.2 checkpoints directory not found: {source_model / 'ckpts'}")
    if not (rembg_model / "config.json").is_file():
        raise FileNotFoundError(f"Local RMBG model is incomplete: {rembg_model}")
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_link = output_dir / "ckpts"
    if checkpoint_link.exists() or checkpoint_link.is_symlink():
        if not checkpoint_link.is_symlink() or checkpoint_link.resolve() != (source_model / "ckpts").resolve():
            raise FileExistsError(f"Unexpected existing checkpoint path: {checkpoint_link}")
    else:
        checkpoint_link.symlink_to(source_model / "ckpts", target_is_directory=True)
    for name in ("pipeline.json", "texturing_pipeline.json"):
        source = source_model / name
        if source.is_file():
            patch_config(source, output_dir / name, rembg_model)
    report = {
        "source_model": str(source_model),
        "local_overlay": str(output_dir),
        "checkpoint_link": str(checkpoint_link),
        "rembg_model": str(rembg_model),
        "pipeline_config": str(output_dir / "pipeline.json"),
    }
    (output_dir / "local_overlay.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
