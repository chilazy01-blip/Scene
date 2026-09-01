from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .assets import bridge_health, generate_trellis_asset
from .content_chain import (
    build_generation_contract,
    content_hash,
    make_artifact_certificate,
    verify_artifact_certificate,
)
from .io_utils import write_json
from .policies import OBJECT_DEFINITIONS


ARCHITECTURE_ASSET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "door": {
        "dimensions": [0.9, 0.08, 2.1],
        "placement_type": "wall_opening",
    },
}
PILOT_ASSET_DEFINITIONS = {
    **OBJECT_DEFINITIONS,
    **ARCHITECTURE_ASSET_DEFINITIONS,
}


def validate_pilot_report(
    report: dict[str, Any], expected_generation_contract: dict[str, Any]
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not bool(report.get("ok")):
        reasons.append("pilot_not_ok")
    actual_contract = report.get("generation_contract")
    if not isinstance(actual_contract, dict) or actual_contract.get("content_key") != expected_generation_contract.get("content_key"):
        reasons.append("generation_contract_mismatch")
    artifact = Path(str(report.get("asset_glb") or ""))
    reference = Path(str(report.get("reference_image") or ""))
    if not artifact.is_file() or not reference.is_file():
        reasons.append("artifact_or_reference_missing")
        return False, reasons
    certificate = report.get("content_certificate")
    valid, certificate_reasons = verify_artifact_certificate(
        certificate if isinstance(certificate, dict) else {},
        artifact,
        upstream={
            "generation_contract": actual_contract,
            "generation_metadata_hash": content_hash(report.get("generation")),
        },
        rules={"kind": "trellis_single_asset_pilot", "inspection_version": 1},
        evidence={"reference_image": reference},
    )
    if not valid:
        reasons.extend(certificate_reasons)
    return not reasons, reasons


def inspect_glb(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "ok": path.is_file() and path.stat().st_size > 0,
        "path": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
    }
    if not report["ok"]:
        return report
    try:
        import trimesh

        loaded = trimesh.load(path, force="scene")
        bounds = loaded.bounds.tolist() if loaded.bounds is not None else None
        extents = loaded.extents.tolist() if loaded.extents is not None else None
        vertex_count = sum(
            len(getattr(geometry, "vertices", ()))
            for geometry in loaded.geometry.values()
        )
        face_count = sum(
            len(getattr(geometry, "faces", ()))
            for geometry in loaded.geometry.values()
        )
        report.update(
            {
                "trimesh_load_ok": True,
                "geometry_count": len(loaded.geometry),
                "vertex_count": vertex_count,
                "face_count": face_count,
                "bounds": bounds,
                "raw_extents": extents,
            }
        )
    except Exception as exc:
        report.update({"trimesh_load_ok": False, "inspection_error": str(exc)})
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate exactly one staging asset through the local TRELLIS.2 bridge."
    )
    parser.add_argument("--category", choices=sorted(PILOT_ASSET_DEFINITIONS), required=True)
    parser.add_argument("--object-id")
    parser.add_argument("--asset-prompt")
    parser.add_argument("--reference-image", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trellis-url", default=os.environ.get("SAGE_TRELLIS_URL", "http://127.0.0.1:8082"))
    parser.add_argument("--pipeline-type", choices=("512", "1024", "1024_cascade", "1536_cascade"), default="512")
    parser.add_argument("--preprocess-image", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--seed", type=int, default=2601)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--steps", type=int, default=12)
    parser.add_argument("--texture-size", type=int, default=512)
    parser.add_argument("--decimation-target", type=int, default=500000)
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--model-fingerprint",
        default=os.environ.get("SAGE_TRELLIS_MODEL_FINGERPRINT", "unfrozen-local-trellis-model"),
    )
    parser.add_argument(
        "--rmbg-fingerprint",
        default=os.environ.get("SAGE_RMBG_MODEL_FINGERPRINT", "unfrozen-local-rmbg-model"),
    )
    parser.add_argument(
        "--code-version",
        default=os.environ.get("SAGE_GENERATION_CODE_VERSION", "unfrozen-scene-v2-code"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    reference_image = args.reference_image.expanduser().resolve()
    if not reference_image.is_file():
        raise FileNotFoundError(f"Reference image not found: {reference_image}")
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    object_id = args.object_id or f"pilot_{args.category}"
    output_glb = output_dir / f"{object_id}.glb"
    if output_glb.exists() and not args.force:
        raise FileExistsError(f"Pilot output already exists: {output_glb}; pass --force to replace it")
    definition = PILOT_ASSET_DEFINITIONS[args.category]
    width, length, height = definition["dimensions"]
    obj = {
        "id": object_id,
        "category": args.category,
        "dimensions": {"width": width, "length": length, "height": height},
        "asset_prompt": args.asset_prompt
        or (
            f"A single isolated {args.category.replace('_', ' ')}, complete object visible, "
            "realistic materials, clean geometry, neutral background, no room, no floor platform, no text."
        ),
    }
    health = bridge_health(args.trellis_url)
    if not health.get("ok"):
        raise RuntimeError(f"TRELLIS.2 bridge is not healthy at {args.trellis_url}: {health}")
    metadata = generate_trellis_asset(
        obj,
        output_glb,
        trellis_url=args.trellis_url,
        seed=args.seed,
        timeout=args.timeout,
        steps=args.steps,
        texture_size=args.texture_size,
        decimation_target=args.decimation_target,
        pipeline_type=args.pipeline_type,
        preprocess_image=args.preprocess_image,
        reference_image_path=reference_image,
    )
    inspection = inspect_glb(output_glb)
    generation_contract = build_generation_contract(
        category=args.category,
        prompt=str(obj["asset_prompt"]),
        target_dimensions_m=obj["dimensions"],
        seed=args.seed,
        model_fingerprint=args.model_fingerprint,
        rmbg_fingerprint=args.rmbg_fingerprint,
        pipeline_type=args.pipeline_type,
        steps=args.steps,
        texture_size=args.texture_size,
        decimation_target=args.decimation_target,
        preprocess_image=args.preprocess_image,
        code_version=args.code_version,
        reference_image=reference_image,
    )
    content_certificate = make_artifact_certificate(
        output_glb,
        upstream={
            "generation_contract": generation_contract,
            "generation_metadata_hash": content_hash(metadata),
        },
        rules={"kind": "trellis_single_asset_pilot", "inspection_version": 1},
        evidence={"reference_image": reference_image},
    )
    result = {
        "schema": "codex_trellis_single_asset_pilot_v1",
        "ok": bool(inspection.get("ok") and inspection.get("trimesh_load_ok")),
        "qa_status": "pending_visual_review",
        "object": obj,
        "reference_image": str(reference_image),
        "asset_glb": str(output_glb),
        "bridge_health": health,
        "generation": metadata,
        "generation_contract": generation_contract,
        "content_certificate": content_certificate,
        "inspection": inspection,
        "curated_manifest_candidate": {
            "asset_id": object_id,
            "category": args.category,
            "styles": [],
            "qa_status": "pending_review",
            "glb_path": str(output_glb),
            "dimensions": obj["dimensions"],
        },
    }
    write_json(output_dir / f"{object_id}_pilot_report.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["ok"]:
        raise RuntimeError(f"Generated GLB failed structural inspection: {output_glb}")


if __name__ == "__main__":
    main()
