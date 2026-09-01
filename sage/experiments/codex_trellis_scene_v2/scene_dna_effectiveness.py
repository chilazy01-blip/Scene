from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .assets import generate_trellis_asset
from .io_utils import read_json, write_json
from .scene_dna_multiview import render_and_evaluate_generated_asset


def _candidate_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    score = attempt.get("scene_dna_candidate_score")
    score = score if isinstance(score, dict) else {}
    return {
        "attempt": int(attempt.get("attempt", -1)),
        "reference_job_id": str(attempt.get("reference_job_id") or ""),
        "prepared_image_path": str(attempt.get("prepared_image_path") or ""),
        "scene_dna_candidate_score": float(score.get("score", 0.0) or 0.0),
        "palette_score": float(score.get("palette_score", 0.0) or 0.0),
        "detail_score": float(score.get("detail_score", 0.0) or 0.0),
    }


def _evaluation_summary(report: dict[str, Any]) -> dict[str, Any]:
    gate = report.get("structure_gate")
    gate = gate if isinstance(gate, dict) else {}
    reference = report.get("reference_appearance")
    reference = reference if isinstance(reference, dict) else {}
    consistency = report.get("opposite_view_consistency")
    consistency = consistency if isinstance(consistency, dict) else {}
    normalization = report.get("normalization")
    normalization = normalization if isinstance(normalization, dict) else {}
    scale_gate = report.get("scale_anisotropy_gate")
    scale_gate = scale_gate if isinstance(scale_gate, dict) else {}
    hard_geometry_gate_passed = bool(
        report.get(
            "hard_geometry_gate_passed",
            bool(report.get("structure_gate_passed"))
            and bool(consistency.get("passes"))
            and bool(scale_gate.get("passes")),
        )
    )
    return {
        "evaluated": bool(report.get("evaluated")),
        "automated_pixel_multiview_pass": bool(
            report.get("automated_pixel_multiview_pass")
        ),
        "acceptance": str(report.get("acceptance") or ""),
        "automated_score": float(report.get("automated_score", 0.0) or 0.0),
        "mean_style_score": float(report.get("mean_style_score", 0.0) or 0.0),
        "minimum_view_style_score": float(
            report.get("minimum_view_style_score", 0.0) or 0.0
        ),
        "structure_gate_passed": bool(report.get("structure_gate_passed")),
        "hard_geometry_gate_passed": hard_geometry_gate_passed,
        "compact_silhouette_passed": bool(
            gate.get("compact_silhouette_passed", True)
        ),
        "reference_appearance_score": float(reference.get("score", 0.0) or 0.0),
        "minimum_opposite_view_consistency": float(
            consistency.get("minimum_pair_score", 0.0) or 0.0
        ),
        "axis_scale_anisotropy": float(
            normalization.get("axis_scale_anisotropy", 0.0) or 0.0
        ),
        "contact_sheet_path": str(report.get("contact_sheet_path") or ""),
        "report_path": str(report.get("report_path") or ""),
    }


def compare_effectiveness(
    baseline_report: dict[str, Any],
    selected_report: dict[str, Any],
) -> dict[str, Any]:
    """Compare branches conservatively; pixel metrics never prove semantic style."""

    baseline = _evaluation_summary(baseline_report)
    selected = _evaluation_summary(selected_report)
    score_delta = round(
        selected["automated_score"] - baseline["automated_score"], 6
    )
    style_delta = round(
        selected["mean_style_score"] - baseline["mean_style_score"], 6
    )
    baseline_pass = baseline["automated_pixel_multiview_pass"]
    selected_pass = selected["automated_pixel_multiview_pass"]
    selected_structure = selected["structure_gate_passed"]
    baseline_structure = baseline["structure_gate_passed"]
    selected_hard_geometry = selected["hard_geometry_gate_passed"]
    baseline_hard_geometry = baseline["hard_geometry_gate_passed"]

    if selected_pass and not baseline_pass:
        verdict = "positive_effect"
        reason = "SceneDNA changed the generated asset from automated failure to pass."
    elif baseline_pass and not selected_pass:
        verdict = "negative_effect"
        reason = "SceneDNA changed the generated asset from automated pass to failure."
    elif selected_hard_geometry and not baseline_hard_geometry:
        verdict = "positive_effect"
        reason = "SceneDNA repaired a hard geometry gate failure."
    elif baseline_hard_geometry and not selected_hard_geometry:
        verdict = "negative_effect"
        reason = "SceneDNA introduced a hard geometry gate failure."
    elif not selected_hard_geometry and not baseline_hard_geometry:
        verdict = "both_failed_hard_geometry"
        reason = "Neither branch is eligible because both failed hard geometry gates."
    elif score_delta >= 0.02:
        verdict = "positive_effect"
        reason = "SceneDNA improved the controlled automated score by at least 0.02."
    elif score_delta <= -0.02:
        verdict = "negative_effect"
        reason = "SceneDNA reduced the controlled automated score by at least 0.02."
    else:
        verdict = "inconclusive_or_small_effect"
        reason = "The controlled automated-score change is smaller than 0.02."

    return {
        "baseline": baseline,
        "scene_dna_selected": selected,
        "deltas_selected_minus_baseline": {
            "automated_score": score_delta,
            "mean_style_score": style_delta,
            "reference_appearance_score": round(
                selected["reference_appearance_score"]
                - baseline["reference_appearance_score"],
                6,
            ),
            "minimum_opposite_view_consistency": round(
                selected["minimum_opposite_view_consistency"]
                - baseline["minimum_opposite_view_consistency"],
                6,
            ),
            "axis_scale_anisotropy": round(
                selected["axis_scale_anisotropy"]
                - baseline["axis_scale_anisotropy"],
                6,
            ),
        },
        "automated_verdict": verdict,
        "verdict_reason": reason,
        "semantic_review_required": True,
    }


def _write_ab_contact_sheet(
    baseline_path: Path, selected_path: Path, output_path: Path
) -> None:
    images: list[tuple[str, Image.Image]] = []
    for label, path in (
        ("A: first candidate baseline", baseline_path),
        ("B: SceneDNA-selected candidate", selected_path),
    ):
        with Image.open(path) as source:
            images.append((label, source.convert("RGB")))
    width = max(image.width for _, image in images)
    row_height = max(image.height for _, image in images) + 36
    canvas = Image.new("RGB", (width, row_height * 2), (232, 232, 232))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(images):
        x = (width - image.width) // 2
        y = index * row_height
        canvas.paste(image, (x, y))
        draw.text((12, y + image.height + 10), label, fill=(20, 20, 20))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)


def run_effectiveness_test(
    source_run: Path,
    output_dir: Path,
    *,
    trellis_url: str,
    blender_bin: Path,
    object_id: str | None = None,
    timeout: float = 1800.0,
    resolution: int = 420,
) -> dict[str, Any]:
    """Run a same-candidates, same-seed A/B test of SceneDNA 2D selection."""

    source_run = source_run.resolve()
    output_dir = output_dir.resolve()
    resolution_path = source_run / "asset_resolution.json"
    resolution_report = read_json(resolution_path)
    if object_id is None:
        candidates = [
            str(item.get("object_id") or "")
            for item in resolution_report.get("results", [])
            if isinstance(item, dict)
            and isinstance(item.get("metadata"), dict)
            and len(
                item["metadata"].get("bridge_metadata", {}).get(
                    "reference_attempts", []
                )
            )
            >= 2
        ]
        if len(candidates) != 1:
            raise ValueError(
                "Specify --object-id when the source run does not have exactly one "
                "generated object with multiple 2D candidates"
            )
        object_id = candidates[0]
    metadata_path = source_run / "assets_staged" / f"{object_id}.json"
    metadata = read_json(metadata_path)
    contract = read_json(Path(str(resolution_report["scene_dna_contract"])))
    obj = metadata["object"]
    request = metadata["request"]
    bridge = metadata["bridge_metadata"]
    attempts = bridge.get("reference_attempts", [])
    if not isinstance(attempts, list) or len(attempts) < 2:
        raise ValueError("The source run must contain at least two reference attempts")
    baseline_attempt = min(attempts, key=lambda item: int(item.get("attempt", 0)))
    selected_job_id = str(bridge.get("selected_reference_job_id") or "")
    selected_attempt = next(
        (
            attempt
            for attempt in attempts
            if str(attempt.get("reference_job_id") or "") == selected_job_id
        ),
        None,
    )
    if selected_attempt is None:
        raise ValueError("Cannot identify the SceneDNA-selected reference attempt")
    if baseline_attempt is selected_attempt:
        raise ValueError("SceneDNA selected the first candidate; this run has no A/B contrast")

    baseline_reference = Path(str(baseline_attempt["prepared_image_path"]))
    selected_reference = Path(str(selected_attempt["prepared_image_path"]))
    selected_source_glb = source_run / "assets_staged" / f"{obj['id']}.glb"
    for required in (baseline_reference, selected_reference, selected_source_glb):
        if not required.is_file():
            raise FileNotFoundError(required)

    baseline_asset_dir = output_dir / "a_first_candidate" / "assets"
    selected_asset_dir = output_dir / "b_scene_dna_selected" / "assets"
    baseline_glb = baseline_asset_dir / f"{obj['id']}.glb"
    selected_glb = selected_asset_dir / f"{obj['id']}.glb"
    baseline_asset_dir.mkdir(parents=True, exist_ok=True)
    selected_asset_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(selected_source_glb, selected_glb)

    generation = generate_trellis_asset(
        obj,
        baseline_glb,
        trellis_url=trellis_url,
        seed=int(request["seed"]),
        timeout=timeout,
        steps=int(request["sparse_steps"]),
        texture_size=int(request["texture_size"]),
        decimation_target=int(request["decimation_target"]),
        pipeline_type=str(request["pipeline_type"]),
        preprocess_image=bool(request["preprocess_image"]),
        reference_image_path=baseline_reference,
    )
    write_json(output_dir / "baseline_generation_metadata.json", generation)

    baseline_report = render_and_evaluate_generated_asset(
        blender_bin=blender_bin,
        asset_dir=baseline_asset_dir,
        output_dir=output_dir / "a_first_candidate" / "multiview",
        obj=obj,
        contract=contract,
        reference_image_path=baseline_reference,
        resolution=resolution,
    )
    selected_report = render_and_evaluate_generated_asset(
        blender_bin=blender_bin,
        asset_dir=selected_asset_dir,
        output_dir=output_dir / "b_scene_dna_selected" / "multiview",
        obj=obj,
        contract=contract,
        reference_image_path=selected_reference,
        resolution=resolution,
    )
    comparison = compare_effectiveness(baseline_report, selected_report)
    contact_sheet = output_dir / "scene_dna_effectiveness_contact_sheet.png"
    _write_ab_contact_sheet(
        Path(baseline_report["contact_sheet_path"]),
        Path(selected_report["contact_sheet_path"]),
        contact_sheet,
    )
    baseline_candidate = _candidate_summary(baseline_attempt)
    selected_candidate = _candidate_summary(selected_attempt)
    report = {
        "schema": "codex_trellis_scene_dna_effectiveness_v1",
        "experiment": "first-candidate baseline versus SceneDNA-selected candidate",
        "controlled_variables": {
            "same_2d_candidate_batch": True,
            "same_object_prompt": True,
            "same_trellis_seed": int(request["seed"]),
            "same_trellis_pipeline": str(request["pipeline_type"]),
            "same_trellis_steps": int(request["sparse_steps"]),
            "same_texture_size": int(request["texture_size"]),
            "same_decimation_target": int(request["decimation_target"]),
            "same_requested_dimensions": obj.get("requested_dimensions"),
            "same_multiview_evaluator": True,
            "only_intended_difference": "2D reference candidate selected for TRELLIS.2",
        },
        "source_run": str(source_run),
        "scene_dna_contract_hash": contract.get("contract_hash"),
        "candidates": {
            "baseline_first": baseline_candidate,
            "scene_dna_selected": selected_candidate,
            "score_delta_selected_minus_baseline": round(
                selected_candidate["scene_dna_candidate_score"]
                - baseline_candidate["scene_dna_candidate_score"],
                6,
            ),
        },
        "comparison": comparison,
        "artifacts": {
            "baseline_glb": str(baseline_glb),
            "scene_dna_selected_glb": str(selected_glb),
            "contact_sheet": str(contact_sheet),
        },
        "limitations": [
            "This is one object, one candidate batch, and one TRELLIS.2 seed.",
            "The automated evaluator checks pixels, silhouette, fragmentation, and scale; it does not verify semantic category or human-perceived style.",
            "A multi-category, multi-seed benchmark and blinded human ratings are required for a general usefulness claim.",
        ],
    }
    write_json(output_dir / "scene_dna_effectiveness_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a controlled real-generation A/B test of SceneDNA selection."
    )
    parser.add_argument("--source-run", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trellis-url", default="http://127.0.0.1:8082")
    parser.add_argument("--blender", required=True, type=Path)
    parser.add_argument("--object-id")
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--resolution", type=int, default=420)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_effectiveness_test(
        args.source_run,
        args.output_dir,
        trellis_url=str(args.trellis_url),
        blender_bin=args.blender,
        object_id=args.object_id,
        timeout=float(args.timeout),
        resolution=int(args.resolution),
    )
    print(json.dumps(report["comparison"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
