from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


REFERENCE_IMAGE_SCHEMA = "codex_trellis_flux_reference_image_v1"


def generate_flux1_schnell_reference(
    prompt: str,
    model_path: Path,
    output_path: Path,
    *,
    width: int = 768,
    height: int = 768,
    steps: int = 4,
    seed: int = 20260724,
) -> dict[str, Any]:
    import torch
    from diffusers import FluxPipeline

    if not torch.cuda.is_available():
        raise RuntimeError("FLUX.1-schnell reference generation requires CUDA")
    model_path = model_path.expanduser().resolve()
    if not (model_path / "model_index.json").is_file():
        raise FileNotFoundError(model_path / "model_index.json")
    if width % 16 or height % 16:
        raise ValueError("width and height must be divisible by 16")
    if steps < 1:
        raise ValueError("steps must be positive")

    started = time.perf_counter()
    pipeline = FluxPipeline.from_pretrained(
        str(model_path),
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    pipeline.enable_model_cpu_offload()
    pipeline.set_progress_bar_config(disable=True)
    loaded_seconds = time.perf_counter() - started
    inference_started = time.perf_counter()
    image = pipeline(
        prompt=prompt,
        width=int(width),
        height=int(height),
        num_inference_steps=int(steps),
        guidance_scale=0.0,
        max_sequence_length=256,
        generator=torch.Generator(device="cuda").manual_seed(int(seed)),
    ).images[0]
    inference_seconds = time.perf_counter() - inference_started
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return {
        "schema": REFERENCE_IMAGE_SCHEMA,
        "model_family": "FLUX.1-schnell",
        "model_path": str(model_path),
        "prompt": prompt,
        "output_path": str(output_path),
        "width": int(width),
        "height": int(height),
        "steps": int(steps),
        "guidance_scale": 0.0,
        "max_sequence_length": 256,
        "seed": int(seed),
        "model_load_seconds": round(float(loaded_seconds), 6),
        "inference_seconds": round(float(inference_seconds), 6),
        "total_seconds": round(float(time.perf_counter() - started), 6),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate one deterministic FLUX.1-schnell scene reference image."
    )
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--output-image", required=True, type=Path)
    parser.add_argument("--metadata-output", type=Path)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260724)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_path = args.output_image.expanduser().resolve()
    if output_path.exists() and not args.overwrite:
        raise FileExistsError(output_path)
    prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError("reference prompt must not be empty")
    report = generate_flux1_schnell_reference(
        prompt,
        args.model_path,
        output_path,
        width=int(args.width),
        height=int(args.height),
        steps=int(args.steps),
        seed=int(args.seed),
    )
    metadata_path = (
        args.metadata_output.expanduser().resolve()
        if args.metadata_output
        else output_path.with_suffix(".json")
    )
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
