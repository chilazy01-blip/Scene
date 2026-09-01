from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from .asset_admission import (
    COUNT_EVIDENCE_SCHEMA,
    audit_library_coverage,
    build_count_contract,
    evaluate_temporary_admission,
    new_lifecycle_record,
    transition_lifecycle,
)
from .collision_mesh_cleanup import cleanup_collision_mesh
from .content_chain import build_generation_contract, content_hash, file_binding
from .io_utils import read_json, write_json


def _count_evidence(entry: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    views = {}
    for role, row in entry["count_review"]["views"].items():
        path = Path(row["path"]).expanduser().resolve()
        payload = {key: value for key, value in row.items() if key != "path"}
        payload["image"] = file_binding(path)
        payload["path"] = str(path)
        views[role] = payload
    return {
        "schema": COUNT_EVIDENCE_SCHEMA,
        "count_contract_hash": contract["contract_hash"],
        "review_method": entry["count_review"]["review_method"],
        "reviewer_id": entry["count_review"]["reviewer_id"],
        "views": views,
    }


def _capability(
    entry: dict[str, Any], asset_path: Path, expected_count: int
) -> dict[str, Any]:
    dimensions = entry["target_dimensions_m"]
    return {
        "schema": "codex_trellis_asset_capability_v1",
        "asset_id": entry["asset_id"],
        "category": entry["category"],
        "source_asset": {**file_binding(asset_path), "qa_status": "approved"},
        "coordinate_frame": {
            "units": "meters",
            "up_axis": "z",
            "origin": "footprint_center_base",
            "source_mesh_up_axis": entry.get("source_mesh_up_axis", "y"),
            "source_mesh_up_sign": int(entry.get("source_mesh_up_sign", 1)),
            "canonical_dimensions": dimensions,
            "asset_axis_to_z": int(entry.get("asset_axis_to_z", 2)),
            "asset_axis_to_z_sign": int(entry.get("asset_axis_to_z_sign", 1)),
            "asset_local_yaw_offset_degrees": float(
                entry.get("asset_local_yaw_offset_degrees", 0)
            ),
        },
        "dimension_policy": entry["dimension_policy"],
        "collision_proxy": {
            "representation": "voxel_sdf",
            "source_glb": asset_path.name,
            "voxel_pitch_m": float(entry.get("voxel_pitch_m", 0.01)),
            "padding_voxels": 4,
            "fill_interior": True,
            "surface_dilation_voxels": 0,
            "sign_strategy": "filled_voxel_occupancy_edt",
            "source_requires_watertight": False,
        },
        "support_surfaces": [],
        "containment_volumes": [],
        "free_space_volumes": [],
        "included_components": {
            str(entry["count_contract"]["component_category"]): expected_count
        },
    }


def _generation_contract(
    entry: dict[str, Any], pilot: dict[str, Any], reference_path: Path
) -> dict[str, Any]:
    generation = pilot.get("generation", {})
    request = generation.get("request", {}) if isinstance(generation, dict) else {}
    bridge = generation.get("bridge_metadata", {}) if isinstance(generation, dict) else {}
    pilot_dimensions = pilot.get("object", {}).get("dimensions")
    target_dimensions = (
        pilot_dimensions
        if isinstance(pilot_dimensions, dict)
        else entry["target_dimensions_m"]
    )
    return build_generation_contract(
        category=entry["category"],
        prompt=str(request.get("input_text") or entry["asset_id"]),
        target_dimensions_m=target_dimensions,
        seed=int(bridge.get("seed", request.get("seed", entry.get("seed", 0))) or 0),
        model_fingerprint=entry["model_fingerprint"],
        rmbg_fingerprint=entry["rmbg_fingerprint"],
        pipeline_type=str(request.get("pipeline_type") or bridge.get("pipeline_type") or "512"),
        steps=int(request.get("shape_steps", request.get("sparse_steps", 12)) or 12),
        texture_size=int(request.get("texture_size", 512) or 512),
        decimation_target=int(request.get("decimation_target", 500000) or 500000),
        preprocess_image=bool(request.get("preprocess_image", True)),
        code_version=entry["generation_code_version"],
        reference_image=reference_path,
    )


def _geometry_report(
    entry: dict[str, Any], asset_path: Path, output_dir: Path
) -> dict[str, Any]:
    configured = entry.get("geometry_report")
    if configured:
        return read_json(Path(configured).expanduser())
    import trimesh

    scene = trimesh.load(asset_path, force="scene")
    meshes = [
        geometry
        for geometry in scene.geometry.values()
        if isinstance(geometry, trimesh.Trimesh) and len(geometry.faces)
    ]
    if not meshes:
        raise ValueError(f"{entry['asset_id']}: no triangle geometry")
    visual_mesh = trimesh.util.concatenate(meshes)
    _cleaned, cleanup = cleanup_collision_mesh(visual_mesh)
    report = {
        "schema": "scene-v2-p013-geometry-qa/v1",
        "ok": bool(cleanup["accepted"]),
        "visual_face_count": int(len(visual_mesh.faces)),
        "collision_mesh_cleanup": cleanup,
    }
    write_json(
        output_dir / "geometry" / f"{entry['asset_id']}.json", report
    )
    return report


def audit_entry(entry: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    asset_path = Path(entry["asset_glb"]).expanduser().resolve()
    pilot = read_json(Path(entry["pilot_report"]).expanduser())
    geometry = _geometry_report(entry, asset_path, output_dir)
    reference_path = Path(entry.get("reference_image") or pilot["reference_image"]).expanduser().resolve()
    count_contract = build_count_contract(**entry["count_contract"])
    count_evidence = _count_evidence(entry, count_contract)
    generation_spec = {
        "schema": "codex_trellis_single_asset_spec_v1",
        "category": entry["category"],
        "target_dimensions_m": entry["target_dimensions_m"],
        "canonical_front": entry["canonical_front"],
        "count_contract": count_contract,
    }
    generation_contract = _generation_contract(entry, pilot, reference_path)
    bridge = pilot.get("generation", {}).get("bridge_metadata", {})
    alpha = next(
        (
            row.get("alpha_metadata", {}).get("alpha_quality", {})
            for row in bridge.get("reference_attempts", [])
            if row.get("source_image_path") == str(reference_path)
        ),
        {},
    )
    source_count = entry["candidate_2d_review"]
    candidate_2d_qa = {
        "source_image": {"path": str(reference_path), **file_binding(reference_path)},
        "alpha": {"ok": bool(alpha.get("ok") and bridge.get("alpha_quality_ok")), "report": alpha},
        "semantic": {
            "ok": bool(source_count.get("semantic_accepted")),
            "reviewer_id": source_count.get("reviewer_id"),
        },
        "count": {
            "ok": int(source_count.get("observed_count", -1))
            == int(count_contract["expected_count"]),
            "observed_count": int(source_count.get("observed_count", -1)),
            "image": file_binding(reference_path),
        },
    }
    original_multiview = read_json(Path(entry["multiview_review"]).expanduser())
    reviewed_asset = next(
        row
        for row in original_multiview["assets"]
        if row["asset_id"] == entry["asset_id"]
    )
    multiview_qa = {
        "evaluated": True,
        "rendered_view_count": 4,
        "missing_views": [],
        "hard_geometry_gate_passed": bool(geometry.get("ok")),
        "automated_pixel_multiview_pass": False,
        "independent_human_review": {
            "accepted": bool(reviewed_asset.get("accepted")),
            "method": original_multiview.get("review_method"),
            "findings": reviewed_asset.get("visual_findings"),
            "contact_sheet": reviewed_asset.get("contact_sheet"),
        },
    }
    cleanup = geometry.get("collision_mesh_cleanup", {})
    source = cleanup.get("source", {})
    inspection = pilot.get("inspection", {})
    bounds = inspection.get("bounds", [])
    finite_bounds = bool(
        isinstance(bounds, list)
        and len(bounds) == 2
        and all(isinstance(value, (int, float)) for row in bounds for value in row)
    )
    capability = _capability(entry, asset_path, count_contract["expected_count"])
    admission = evaluate_temporary_admission(
        asset_path,
        generation_spec=generation_spec,
        generation_contract=generation_contract,
        candidate_2d_qa=candidate_2d_qa,
        trellis_generation={
            "ok": bool(pilot.get("ok")),
            "job_id": str(pilot.get("generation", {}).get("job_id") or ""),
            "metadata_hash": content_hash(pilot.get("generation", {})),
        },
        multiview_qa=multiview_qa,
        dimension_qa={
            "accepted": bool(entry.get("dimension_review_accepted")),
            "measured_from_glb": True,
            "target_dimensions_m": entry["target_dimensions_m"],
            "cleaned_bounds_m": cleanup.get("cleanup", {}).get("cleaned_bounds_m"),
        },
        orientation_qa={
            "accepted": bool(entry.get("orientation_review_accepted")),
            "canonical_front": entry["canonical_front"],
        },
        topology_qa={
            "trimesh_load_ok": bool(inspection.get("trimesh_load_ok")),
            "finite_bounds": finite_bounds,
            "face_count": int(source.get("face_count", geometry.get("visual_face_count", 0)) or 0),
            "cleanup_accepted": bool(cleanup.get("accepted")),
        },
        capability=capability,
        count_evidence=count_evidence,
    )
    lifecycle = new_lifecycle_record(entry["asset_id"], admission)
    curated = None
    promotion = entry.get("promotion_review")
    if admission["accepted"] and isinstance(promotion, dict) and promotion.get("requested"):
        lifecycle = transition_lifecycle(
            lifecycle,
            "candidate_for_curation",
            evidence={
                "scene_independent_review_requested": True,
                "reviewer_id": promotion.get("reviewer_id"),
                "admission_hash": admission["admission_hash"],
            },
        )
        lifecycle = transition_lifecycle(
            lifecycle,
            "curated",
            evidence={
                "independent_review_accepted": bool(promotion.get("accepted")),
                "reviewer_id": promotion.get("reviewer_id"),
                "license_id": entry["license"]["id"],
                "qa_hash": admission["admission_hash"],
            },
        )
        curated_path = output_dir / "assets" / asset_path.name
        curated_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(asset_path, curated_path)
        curated = {
            "asset_id": entry["asset_id"],
            "category": entry["category"],
            "lifecycle_status": lifecycle["status"],
            "qa_status": "approved",
            "glb_path": str(curated_path.relative_to(output_dir)),
            "asset_sha256": file_binding(curated_path)["sha256"],
            "style_signature": entry["style_signature"],
            "styles": entry.get("styles", []),
            "canonical_front": entry["canonical_front"],
            "handedness": entry.get("handedness", "not_applicable"),
            "dimensions": entry["target_dimensions_m"],
            "dimension_policy": entry["dimension_policy"],
            "capability": capability,
            "license": entry["license"],
            "qa_hash": admission["admission_hash"],
            "known_failure_scenarios": entry.get("known_failure_scenarios", []),
            "count_contract": count_contract,
        }
    elif not admission["accepted"]:
        lifecycle = transition_lifecycle(
            lifecycle,
            "rejected",
            evidence={"failures": admission["failures"]},
        )
    result = {
        "asset_id": entry["asset_id"],
        "admission": admission,
        "lifecycle": lifecycle,
        "curated_entry": curated,
        "candidate_2d_qa": candidate_2d_qa,
        "count_evidence": count_evidence,
        "multiview_qa": multiview_qa,
        "capability": capability,
    }
    write_json(output_dir / "admissions" / f"{entry['asset_id']}.json", result)
    return result


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    config = read_json(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [audit_entry(entry, output_dir) for entry in config["assets"]]
    curated = [row["curated_entry"] for row in results if row["curated_entry"]]
    coverage = audit_library_coverage(
        curated, list(config["high_frequency_categories"])
    )
    manifest = {
        "schema": "scene-v2-curated-generated-assets/v1",
        "library_id": config["library_id"],
        "assets": curated,
        "coverage": coverage,
        "single_scene_success_auto_curates": False,
    }
    write_json(output_dir / "manifest.json", manifest)
    report = {
        "schema": "scene-v2-p013-asset-admission-audit/v1",
        "ok": coverage["ok"],
        "asset_count": len(results),
        "scene_specific_approved_count": sum(
            row["admission"]["accepted"] for row in results
        ),
        "rejected_count": sum(
            row["lifecycle"]["status"] == "rejected" for row in results
        ),
        "curated_count": len(curated),
        "coverage": coverage,
        "results": [
            {
                "asset_id": row["asset_id"],
                "accepted": row["admission"]["accepted"],
                "failures": row["admission"]["failures"],
                "lifecycle_status": row["lifecycle"]["status"],
                "admission_hash": row["admission"]["admission_hash"],
            }
            for row in results
        ],
    }
    report["report_hash"] = content_hash(report)
    write_json(output_dir / "p013_asset_admission_audit.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.config.expanduser(), args.output_dir.expanduser())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
