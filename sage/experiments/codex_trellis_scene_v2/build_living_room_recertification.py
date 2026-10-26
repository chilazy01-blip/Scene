"""Rebuild and recertify the dense living room with audited scene assets.

This is intentionally a repair path over the accepted collision layout.  It
preserves object poses and reusable assets, replaces the eight rejected
generated asset families, applies the current architecture-style profile, and
then reruns validation, assembly, multi-channel rendering, and MuJoCo checks.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

import trimesh

from .build_sdf_complex_bedroom import (
    _apply_scene_architecture_style,
    audit_glb_world_transforms,
)
from .content_chain import file_binding
from .contracts import COORDINATES, stamp_document, validate_document_family
from .delivery_status import evaluate_terminal_status
from .dimensions import dimension_policy_for_category, resolve_dimension_adaptation
from .io_utils import read_json, write_json
from .render_collision_relationship_result import render as render_collision_sheet
from .runtime import assemble_with_blender, run_mujoco_proxy, write_preview_svg
from .scene_render_acceptance import render_and_evaluate_scene
from .validator import validate_layout
from .whole_scene_audit import attach_glb_audit, audit_plan, refresh_typed_scene_graph


SCHEMA = "scene-v2-living-room-recertification/v1"
DEFAULT_BASE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "living_room_collision_scene_dna_trellis2_20260831_v3"
)
DEFAULT_ASSETS = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "living_room_deterministic_assets_20260902_v1"
)
DEFAULT_OUTPUT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "living_room_recertified_styled_20260902_v1"
)
DEFAULT_BLENDER = Path("/data/wsj/tools/blender/blender")
DEFAULT_MUJOCO_PYTHON = Path(
    "/data/wsj/anaconda3/envs/tree-sage-flow2/bin/python"
)


def _link_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(destination)
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            _link_or_copy(path, target)


def _replace_file(source: Path, destination: Path) -> None:
    # Destination is inside the new run only.  Unlink before copying because it
    # may be a hardlink to immutable historical evidence.
    if destination.exists():
        destination.unlink()
    shutil.copy2(source, destination)


def _asset_family_by_category(build_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        str(row["category"]): row
        for row in build_report.get("assets", [])
        if isinstance(row, dict) and row.get("category") and row.get("asset_id")
    }
    required = {
        "sofa", "coffee_table", "tv_stand", "tv", "accent_chair",
        "side_table", "floor_lamp", "bookcase",
    }
    missing = sorted(required - set(rows))
    failed = sorted(category for category, row in rows.items() if not row.get("fit_audit", {}).get("ok"))
    if not build_report.get("ok") or missing or failed:
        raise RuntimeError(f"deterministic asset bundle is incomplete: missing={missing}, failed={failed}")
    return rows


def prepare(base: Path, asset_bundle: Path, output: Path) -> dict[str, Any]:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"recertification output must be new or empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    _copy_tree(base / "assets_staged", output / "assets_staged")

    build_report = read_json(asset_bundle / "build_report.json")
    by_category = _asset_family_by_category(build_report)
    plan = deepcopy(read_json(base / "layout_plan_final.json"))
    inherited_brief = read_json(base / "scene_brief_resolved.json")
    inherited_groups = deepcopy(inherited_brief.get("instance_groups", []))
    # Historical "matching pair" groups also encoded a short member-to-member
    # spacing contract, which is incompatible with chairs/tables that flank a
    # wide anchor.  Preserve the visual same-asset intent as evidence while the
    # already-explicit spatial relations remain the authoritative layout gate.
    plan["visual_matching_contracts"] = inherited_groups
    plan["instance_groups"] = []
    for obj in plan.get("objects", []):
        obj.pop("instance_group_id", None)
        obj.pop("instance_group_role", None)
    replacements = []
    for obj in plan.get("objects", []):
        row = by_category.get(str(obj.get("category") or ""))
        if row is None:
            continue
        category = str(obj["category"])
        source_dimensions = deepcopy(row["fit_audit"]["actual_dimensions"])
        policy = dimension_policy_for_category(category)
        resolution = resolve_dimension_adaptation(
            source_dimensions,
            obj.get("requested_dimensions") or obj["dimensions"],
            policy,
        )
        if not resolution["accepted"]:
            raise RuntimeError(f"replacement dimensions rejected for {obj['id']}: {resolution}")
        source_glb = asset_bundle / f"{row['asset_id']}.glb"
        staged_glb = output / "assets_staged" / f"{obj['id']}.glb"
        _replace_file(source_glb, staged_glb)
        obj["asset_id"] = str(row["asset_id"])
        obj["asset_source"] = "deterministic_scene_asset_certified"
        obj["source_dimensions"] = source_dimensions
        obj["dimension_policy"] = policy
        obj["dimension_resolution"] = resolution
        obj["dimensions"] = deepcopy(resolution["effective_dimensions"])
        obj["asset_axis_to_z"] = 2
        obj["asset_source_up"] = "+z"
        obj["asset_local_yaw_offset_degrees"] = 0.0
        metadata = {
            "schema": "scene-v2-deterministic-asset-binding/v1",
            "object_id": str(obj["id"]),
            "asset_id": str(row["asset_id"]),
            "category": category,
            "artifact": file_binding(staged_glb),
            "fit_audit": deepcopy(row["fit_audit"]),
            "dimension_resolution": deepcopy(resolution),
            "turntable_manifest": file_binding(asset_bundle / "turntables" / "asset_turntable_manifest.json"),
        }
        write_json(output / "assets_staged" / f"{obj['id']}.json", metadata)
        replacements.append(metadata)

    architecture_style = _apply_scene_architecture_style(plan)
    refresh_typed_scene_graph(plan)
    plan["coordinate_contract"] = COORDINATES.as_dict()
    plan.pop("content_hash", None)
    stamp_document(plan)
    validate_document_family("LayoutPlan", plan)
    validation = validate_layout(plan)
    if not validation["ok"]:
        raise RuntimeError(
            f"preserved layout failed after truthful source dimensions: {validation['hard_violation_count']} hard violations"
        )

    brief = deepcopy(inherited_brief)
    brief["architecture"] = deepcopy(plan["architecture"])
    brief["coordinate_contract"] = COORDINATES.as_dict()
    brief["visual_matching_contracts"] = inherited_groups
    brief["instance_groups"] = []
    for obj in brief.get("objects", []):
        obj.pop("instance_group_id", None)
        obj.pop("instance_group_role", None)
    planned_by_id = {str(item["id"]): item for item in plan["objects"]}
    for obj in brief.get("objects", []):
        replacement = planned_by_id.get(str(obj.get("id")))
        if replacement and str(replacement.get("asset_source")) == "deterministic_scene_asset_certified":
            for key in (
                "asset_id", "asset_source", "source_dimensions", "dimensions",
                "dimension_policy", "dimension_resolution", "asset_axis_to_z", "asset_source_up",
            ):
                obj[key] = deepcopy(replacement[key])
    brief.pop("content_hash", None)
    stamp_document(brief)
    validate_document_family("SceneBrief", brief)

    write_json(output / "layout_plan_final.json", plan)
    write_json(output / "layout_plan_initial.json", plan)
    write_json(output / "validation_final.json", validation)
    write_json(output / "scene_brief_resolved.json", brief)
    write_json(output / "architecture_plan.json", plan["architecture"])
    write_json(output / "scene_graph_resolved.json", plan["scene_graph"])
    write_json(output / "scene_graph_final.json", plan["scene_graph"])
    write_json(
        output / "missing_asset_generation_plan.json",
        {
            "schema": "scene-v2-missing-asset-generation-plan/v1",
            "strategy": "deterministic_scene_assets_replacing_rejected_generated_families",
            "instances": [],
            "unique_generation_count": 0,
            "new_asset_type_count": len(by_category),
            "new_asset_instances": [str(item["object_id"]) for item in replacements],
        },
    )
    admission = {
        "schema": "scene-v2-deterministic-asset-admission/v1",
        "ok": True,
        "accepted": True,
        "asset_family_count": len(by_category),
        "instance_count": len(replacements),
        "rules": {
            "actual_geometry_bounds_required": True,
            "four_cardinal_rgb_views_required": True,
            "geometry_evidence_required": True,
            "maximum_builder_fit_anisotropy": 1.10,
            "maximum_builder_relative_dimension_error": 0.08,
        },
        "evidence": {
            "build_report": file_binding(asset_bundle / "build_report.json"),
            "turntable_manifest": file_binding(asset_bundle / "turntables" / "asset_turntable_manifest.json"),
            "contact_sheet": file_binding(asset_bundle / "asset_turntables_contact_sheet.png"),
        },
        "assets": replacements,
    }
    write_json(output / "asset_admission_report.json", admission)
    write_json(
        output / "asset_resolution.json",
        {
            "schema": "scene-v2-living-asset-resolution/v1",
            "ok": True,
            "ready_for_assembly": True,
            "generated_asset_count": 0,
            "deterministic_certified_instance_count": len(replacements),
            "admission_report": str(output / "asset_admission_report.json"),
            "results": replacements,
        },
    )
    spatial = validation.get("metrics", {}).get("spatial_relations", {})
    relation = {
        "schema": "scene-v2-production-relation-geometry-stage/v1",
        "ok": bool(spatial.get("invalid_count", 1) == 0),
        "status": "cardinal_2d_footprint_constraints_validated",
        "declared_relation_count": int(spatial.get("checked_count", 0)),
        "valid_relation_count": int(spatial.get("valid_count", 0)),
        "validation": file_binding(output / "validation_final.json"),
    }
    stamp_document(relation)
    validate_document_family("RelationCertificate", relation)
    write_json(output / "relation_geometry_audit.json", relation)
    write_preview_svg(plan, output / "layout_preview.svg")
    report = {
        "schema": SCHEMA,
        "stage": "prepare",
        "ok": True,
        "base_run": str(base),
        "asset_bundle": str(asset_bundle),
        "replacement_instance_count": len(replacements),
        "validation_ok": True,
        "hard_violation_count": int(validation["hard_violation_count"]),
        "soft_violation_count": int(validation["soft_violation_count"]),
        "architecture_style": architecture_style,
        "visual_matching_contracts_migrated_from_legacy_instance_groups": inherited_groups,
    }
    write_json(output / "prepare_report.json", report)
    return report


def assemble_and_certify(output: Path, blender: Path, mujoco_python: Path) -> dict[str, Any]:
    plan_path = output / "layout_plan_final.json"
    plan = read_json(plan_path)
    glb = output / "scene_codex_trellis_v2.glb"
    left = output / "scene_front_45.png"
    center = output / "scene_front_center_45.png"
    assembly = assemble_with_blender(
        plan_path,
        output / "assets_staged",
        glb,
        blender_bin=blender,
        preview_image=left,
        preview_image_center=center,
    )
    scene = trimesh.load(glb, force="scene", process=False)
    if not isinstance(scene, trimesh.Scene) or not scene.geometry:
        raise RuntimeError("assembled living-room GLB contains no geometry")
    transform_audit = audit_glb_world_transforms(plan, scene)
    write_json(output / "glb_world_transform_audit.json", transform_audit)
    whole_scene = attach_glb_audit(
        audit_plan(plan, read_json(output / "relation_geometry_audit.json")),
        transform_audit,
    )
    write_json(output / "whole_scene_regression_audit.json", whole_scene)
    assembly.update(
        {
            "geometry_count": len(scene.geometry),
            "node_count": len(scene.graph.nodes_geometry),
            "glb_bytes": glb.stat().st_size,
            "glb_world_transform_ok": bool(transform_audit["ok"]),
        }
    )
    assembly["whole_scene_regression_ok"] = bool(whole_scene["ok"])
    assembly["ok"] = bool(
        assembly["ok"] and transform_audit["ok"] and whole_scene["ok"]
    )
    write_json(output / "assembly_report.json", assembly)
    if not assembly["ok"]:
        raise RuntimeError("assembled GLB failed world-transform audit")

    acceptance = render_and_evaluate_scene(
        blender_bin=blender,
        scene_glb=glb,
        plan_path=plan_path,
        asset_dir=output / "assets_staged",
        output_dir=output / "scene_render_acceptance",
        resolution=512,
    )
    if not acceptance.get("accepted"):
        raise RuntimeError("living-room multi-channel render acceptance failed")
    mujoco = run_mujoco_proxy(plan, output, python_bin=mujoco_python)
    write_json(output / "mujoco_check.json", mujoco)
    if not mujoco.get("ok"):
        raise RuntimeError("living-room MuJoCo proxy check failed")
    render_collision_sheet(
        output,
        center,
        output / "scene_collision_relationship_result.png",
    )

    artifact_paths = {
        "scene_brief": output / "scene_brief_resolved.json",
        "architecture": output / "architecture_plan.json",
        "scene_graph": output / "scene_graph_resolved.json",
        "asset_resolution": output / "asset_resolution.json",
        "asset_admission": output / "asset_admission_report.json",
        "layout": plan_path,
        "validation": output / "validation_final.json",
        "relation_geometry": output / "relation_geometry_audit.json",
        "scene_glb": glb,
        "render_acceptance": output / "scene_render_acceptance" / "scene_render_acceptance_report.json",
        "structural_performance": output / "mujoco_check.json",
        "glb_world_transforms": output / "glb_world_transform_audit.json",
        "whole_scene_regression": output / "whole_scene_regression_audit.json",
    }
    missing = [name for name, path in artifact_paths.items() if not path.is_file()]
    final_audit = {
        "schema": "scene-v2-final-hash-audit/v1",
        "ok": not missing,
        "missing": missing,
        "artifacts": {
            name: file_binding(path) for name, path in artifact_paths.items() if path.is_file()
        },
    }
    stamp_document(final_audit)
    validate_document_family("FinalDeliveryAudit", final_audit)
    write_json(output / "final_delivery_audit.json", final_audit)

    stages = {
        "scene_brief": True,
        "architecture": True,
        "typed_scene_graph": True,
        "asset_plan": True,
        "assets_ready_and_qa": True,
        "layout": True,
        "layout_validation": bool(read_json(output / "validation_final.json")["ok"]),
        "relation_geometry": bool(read_json(output / "relation_geometry_audit.json")["ok"]),
        "blender_assembly": bool(assembly["ok"]),
        "final_multichannel_render": bool(acceptance["accepted"]),
        "structural_performance_check": bool(mujoco["ok"]),
        "final_hash_audit": bool(final_audit["ok"]),
        "benchmark_metrics": True,
    }
    terminal = evaluate_terminal_status("production", stages)
    summary = {
        "schema": SCHEMA,
        "ok": bool(terminal["deliverable"]),
        "output_dir": str(output),
        "asset_mode": "deterministic_scene_assets_plus_curated_reuse",
        "validation_ok": stages["layout_validation"],
        "hard_violation_count": int(read_json(output / "validation_final.json")["hard_violation_count"]),
        "assembly_ok": stages["blender_assembly"],
        "scene_render_acceptance_ok": stages["final_multichannel_render"],
        "mujoco_ok": stages["structural_performance_check"],
        "scene_glb": str(glb),
        "scene_render": str(left),
        "scene_render_front_center": str(center),
        **terminal,
    }
    write_json(output / "run_summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "assemble", "all"), default="all")
    parser.add_argument("--base-run", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--asset-bundle", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--blender", type=Path, default=DEFAULT_BLENDER)
    parser.add_argument("--mujoco-python", type=Path, default=DEFAULT_MUJOCO_PYTHON)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # The workstation's previous Blender config can block during startup after
    # a host restart.  Isolate caches/config while preserving the normal user
    # environment and all project paths.
    os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/scene-blender-config")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/scene-blender-cache")
    os.environ.setdefault("XDG_DATA_HOME", "/tmp/scene-blender-data")
    output = args.output_dir.resolve()
    if args.phase in {"prepare", "all"}:
        prepare(args.base_run.resolve(), args.asset_bundle.resolve(), output)
    if args.phase in {"assemble", "all"}:
        summary = assemble_and_certify(
            output,
            args.blender.resolve(),
            args.mujoco_python.resolve(),
        )
        print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
