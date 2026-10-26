"""Prepare an actual, source-bound P021 room before dynamics and rendering.

The caller must schedule Blender with the P007 resource guard. This module
never generates furniture, changes an old review, or promotes an asset into
the curated library. A successful result proves assembly/geometry only.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import time
from typing import Any

from . import p019_engineering_scene_validation as engineering
from . import p019_scene_validation as core
from . import runtime
from .asset_admission import new_lifecycle_record
from .asset_source_policy import audit_asset_source_policy
from .content_chain import content_hash, file_binding
from .scene_graph import build_typed_scene_graph, materialize_scene_graph
from .validator import validate_layout


SPEC_SCHEMA = "p021-physics-scene-spec/v1"
SCHEMA = "p021-physics-scene-preparation/v1"
METHODS = ("B0_bound_control", "A_support_priority", "B_explicit_pairs")
ADMITTED = {
    "bookcase_r1": ("bookcase__builtin_imagegen__r1", "bookcase"),
    "bookcase_r2": ("bookcase__builtin_imagegen__r2", "bookcase"),
    "sofa_builtin_r1_engineering": ("sofa__builtin_imagegen__r1", "sofa"),
}
REUSE = {"reuse_mode": "existing_generated_glb", "new_generation": False,
         "auto_curated": False, "asset_lifecycle_status": "generated_for_run"}
require, bound, check_binding = core.require, core.bound, core.check_binding
read_json, write_json = core.read_json, core.write_json


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    require(type(value) in (int, float) and math.isfinite(value), f"{label} must be finite numeric")
    require(not positive or value > 0, f"{label} must be positive")
    return float(value)


def validate_spec(spec: dict[str, Any], inventory: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve exact inventory identities without trusting cached admission flags."""
    require(spec.get("schema") == SPEC_SCHEMA, "unexpected P021 scene specification schema")
    require(isinstance(spec.get("run_id"), str) and spec["run_id"].strip(), "run_id is required")
    require(spec.get("method") in METHODS, "unknown P021 friction method")
    _number(spec.get("floor_mu"), "floor_mu", positive=True)
    require(spec.get("parameter_origin") == "designed_test_coefficient", "friction origin must be a designed test coefficient")
    require("measured_asset_friction" in spec and spec["measured_asset_friction"] is None,
            "P021 has no measured asset friction")
    require(type(spec.get("development")) is bool, "development must be explicitly true or false")
    room = spec.get("room", {})
    require(isinstance(room, dict) and set(room) == {"width", "length", "height"}, "room requires width/length/height only")
    for axis in ("width", "length", "height"):
        _number(room[axis], f"room.{axis}", positive=True)
    simulation = spec.get("simulation", {})
    require(isinstance(simulation, dict), "simulation must be an object")
    for key in ("dt", "settle_s", "action_s", "sample_interval_s"):
        _number(simulation.get(key), f"simulation.{key}", positive=True)
    velocity = simulation.get("initial_velocity_m_s")
    require(isinstance(velocity, list) and len(velocity) == 3, "initial velocity needs three components")
    for index, value in enumerate(velocity):
        _number(value, f"initial_velocity_m_s[{index}]")
    require(velocity[2] == 0, "round1 requires a horizontal sliding action")
    require(simulation["dt"] <= simulation["sample_interval_s"] <= simulation["action_s"],
            "simulation sampling interval must be between dt and action duration")
    require(inventory.get("schema") == "p021-readonly-asset-inventory/v1", "unexpected asset inventory schema")
    entries = inventory.get("selected_assets", [])
    require(isinstance(entries, list) and all(isinstance(row, dict) for row in entries), "inventory assets must be objects")
    inventory_ids = [row.get("inventory_id") for row in entries]
    require(len(set(inventory_ids)) == len(inventory_ids), "duplicate inventory IDs")
    by_inventory = {row["inventory_id"]: row for row in entries}
    objects = spec.get("objects")
    require(isinstance(objects, list) and len(objects) == 2, "round1 requires exactly one bookcase and one sofa")
    selected, seen = [], set()
    for obj in objects:
        require(isinstance(obj, dict) and set(obj) == {"id", "inventory_id", "x", "y", "z", "yaw"},
                "object requires only id/inventory_id/x/y/z/yaw; source dimensions and axes are frozen")
        inventory_id = obj["inventory_id"]
        require(inventory_id in ADMITTED and inventory_id in by_inventory, f"asset is not admitted for round1: {inventory_id}")
        entry = by_inventory[inventory_id]
        expected_id, category = ADMITTED[inventory_id]
        require(entry.get("object_id") == expected_id and entry.get("category") == category,
                "inventory identity/category changed")
        require(obj["id"] == entry["object_id"], "object ID must equal the original inventory object_id")
        require(obj["id"] not in seen, "duplicate scene object ID")
        seen.add(obj["id"])
        for key in ("x", "y", "z", "yaw"):
            _number(obj[key], f"{obj['id']}.{key}")
        # The unchanged P019 inspector compares axis-aligned metric dimensions.
        # A yawed/raised scene needs a separately developed correspondence gate.
        require(obj["yaw"] == 0 and obj["z"] == 0, "round1 requires original yaw=0 and floor bottom z=0")
        require(entry.get("curated") is False, "generated asset cannot be promoted to curated")
        selected.append(entry)
    require({row["category"] for row in selected} == {"bookcase", "sofa"}, "round1 requires exactly one bookcase and one sofa")
    return selected


def _verify_engineering_review(root: Path, frozen: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """Check the selected sofa's actual frozen engineering packet and review."""
    directory = root / "engineering_scene_validation"
    freeze_path = directory / "engineering_frozen.json"
    frozen_engineering = read_json(freeze_path)
    core.sealed_key(frozen_engineering)
    engineering.check_scope(frozen_engineering)
    require(frozen_engineering.get("schema") == "p019-engineering-frozen/v1", "engineering freeze schema mismatch")
    require(read_json(check_binding(frozen_engineering["original_cases"])) == frozen, "engineering original frozen cases changed")
    require(check_binding(frozen_engineering["original_plan"]).resolve() == (root / "frozen_plan.json").resolve(), "engineering original plan changed")
    request_path = check_binding(frozen_engineering["request"])
    request = read_json(request_path)
    require(request == engineering.engineering_request(), "original engineering request changed")
    packet_path = check_binding(frozen_engineering["packets"][row["case"]["provider"]])
    packet = read_json(packet_path)
    core.sealed_key(packet)
    engineering.check_scope(packet)
    require(packet.get("request_content_key") == request["content_key"], "engineering packet request changed")
    require({key: value for key, value in packet.items() if key not in {"content_key", "request_content_key"}} == row,
            "engineering packet no longer matches the original source and scoped facts")
    prepared_path = directory / "engineering_prepared.json"
    prepared = read_json(prepared_path)
    core.sealed_key(prepared)
    engineering.check_scope(prepared)
    require(prepared.get("schema") == "p019-engineering-prepared/v1" and
            prepared.get("engineering_frozen_key") == frozen_engineering["content_key"], "engineering preparation freeze changed")
    review_path = check_binding(prepared["files"][f"asset_review/{row['case']['id']}"])
    engineering.verify_asset_review(read_json(review_path), packet, request)
    return {"mode": "revalidate_existing_explicit_engineering_review",
            "new_visual_judgment": False, "independent_human_validation": None,
            "request_content_key": request["content_key"],
            "evidence": {name: bound(path) for name, path in (
                ("engineering_freeze", freeze_path), ("engineering_request", request_path),
                ("engineering_packet", packet_path), ("engineering_prepared", prepared_path),
                ("engineering_asset_review", review_path))}}


def revalidate_asset(entry: dict[str, Any]) -> dict[str, Any]:
    """Read original P019 evidence and verify it against its original frozen inputs."""
    inventory_id = entry["inventory_id"]
    require(inventory_id in ADMITTED, "conditional or unknown inventory asset is not admitted")
    expected_id, category = ADMITTED[inventory_id]
    require((entry.get("object_id"), entry.get("category")) == (expected_id, category), "inventory identity/category changed")
    check_binding(entry["glb"])
    for binding in entry["entrypoint_files"].values():
        check_binding(binding)
    for binding in entry["current_recursive_evidence_file_bindings"]:
        check_binding(binding)
    case_directory = Path(entry["entrypoint_files"]["asset_object"]["path"]).resolve().parent
    require(case_directory.name == expected_id and case_directory.parent.name == "cases", "original case directory identity changed")
    root = case_directory.parent.parent
    frozen_path, plan_path = root / "frozen_cases.json", root / "frozen_plan.json"
    frozen, original_plan = read_json(frozen_path), read_json(plan_path)
    core.sealed_key(frozen)
    require(content_hash(original_plan) == frozen["preregistration_hash"], "original preregistration changed")
    require(file_binding(plan_path) == frozen["preregistration_file"], "original preregistration bytes changed")
    matches = [case for case in frozen["cases"] if case.get("id") == expected_id]
    require(len(matches) == 1, "original frozen case missing or duplicated")
    case = matches[0]
    require(case["category"] == category and case["provider"] == "builtin_imagegen", "original category/provider changed")
    if category == "sofa":
        row = engineering.verify_engineering_source(root, frozen, case)
        quality = _verify_engineering_review(root, frozen, row)
    else:
        row = core.verify_audit(root, frozen, case)
        quality = {"mode": "revalidate_existing_original_request_review", "new_visual_judgment": False,
                   "independent_human_validation": None,
                   "evidence": {name: row["evidence"][name] for name in ("visual_review", "audit", "audit_certificate")}}
    require(row["asset"] == entry["glb"], "reviewed source differs from the inventoried GLB")
    require(row["case"]["dimensions"] == entry["requested_dimensions_m"], "inventoried dimensions differ from the frozen source request")
    require(row["generation"]["job_id"] == entry["generation_job_id"], "inventoried generation job changed")
    obj = read_json(check_binding(row["evidence"]["asset_object"]))
    require(obj.get("id") == expected_id and obj.get("category") == category and
            obj.get("dimensions") == case["dimensions"], "original asset object identity/dimensions changed")
    expected_orientation = {"asset_axis_to_z": 2, "asset_axis_to_z_sign": 1.0, "asset_local_yaw_offset_degrees": 0.0}
    for key, expected in expected_orientation.items():
        require(obj.get(key) == expected and entry["orientation"].get(key) == expected, f"original audited orientation changed: {key}")
    require(not obj.get("asset_reflection_axis") and not obj.get("footprint_yaw_offset_degrees"), "unreviewed asset reflection/yaw offset")
    require(obj.get("asset_generation_key") == row["generation_key"] and
            obj.get("asset_generation_contract") == row["generation"]["generation_contract"], "asset object generation contract changed")
    row.update(inventory_id=inventory_id, reuse=deepcopy(REUSE),
               prior_quality=deepcopy(entry["prior_quality"]),
               quality_scope=entry["new_request_boundary"], scoped_admission=quality,
               physical_measurements=deepcopy(entry["physics_metadata"]))
    row["evidence"].update(original_frozen_cases=bound(frozen_path), original_frozen_plan=bound(plan_path))
    row["evidence"].update(quality["evidence"])
    return row


def make_plan(spec: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep source normalization intact and apply only requested room placement."""
    require(len(rows) == len(spec["objects"]) and
            {row["case"]["id"] for row in rows} == {obj["id"] for obj in spec["objects"]},
            "plan source object IDs differ from the specification")
    plan = core.make_plan(rows, "builtin_imagegen")
    by_id = {obj["id"]: obj for obj in spec["objects"]}
    for obj in plan["objects"]:
        pose = by_id[obj["id"]]
        obj.update({key: pose[key] for key in ("x", "y", "z", "yaw")})
        obj.update(provenance="p021_frozen_physics_scene_request", **REUSE)
    plan.update(room=deepcopy(spec["room"]), relations=[], scene_purpose="p021_exterior_floor_sliding_comparison",
                p021_scene_spec_hash=content_hash(spec), run_id=spec["run_id"], **REUSE)
    plan["scene_graph"] = materialize_scene_graph(build_typed_scene_graph(plan), plan["objects"])
    return plan


def inspect_final_scene(scene_glb: Path, plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Use the unchanged full geometry comparison and reject extra furniture IDs."""
    expected = [obj["id"] for obj in plan["objects"]]
    require(len(expected) == len(set(expected)), "duplicate layout object IDs")
    require(len(rows) == len(expected) and {row["case"]["id"] for row in rows} == set(expected),
            "geometry source object IDs differ from the layout")
    document, _ = core.glb_document(scene_glb)
    worlds = core.world_matrices(document)
    exported = {document["nodes"][index].get("extras", {}).get("scene_object_id") for index in worlds}
    exported.discard(None)
    require(exported == set(expected), f"final furniture object IDs differ: expected={sorted(expected)}, actual={sorted(map(str, exported))}")
    architecture_names = {"floor", *(f"wall_{wall}_panel_0" for wall in plan.get("architecture", {}).get("walls", []))}
    untagged_meshes = [document["nodes"][index].get("name") for index in worlds
                       if "mesh" in document["nodes"][index] and
                       document["nodes"][index].get("extras", {}).get("scene_object_id") is None]
    require(len(untagged_meshes) == len(set(untagged_meshes)) and
            set(untagged_meshes) <= architecture_names, "unexpected untagged or duplicate architectural mesh")
    result = core.inspect_scene(scene_glb, plan, rows)
    # Geometry correspondence alone cannot detect a root transform changed in
    # a way that preserves a symmetric object's AABB. Validate yaw/scale axes.
    import numpy as np
    for obj in plan["objects"]:
        row = result["objects"][obj["id"]]
        matrix = np.asarray(row["asset_gltf_to_scene_z_up_matrix"], dtype=float)
        linear = matrix[:3, :3] @ core.GLTF_TO_Z[:3, :3].T
        scales = np.diag(linear)
        orientation_ok = bool(np.isfinite(linear).all() and (scales > 0).all() and
                              np.allclose(linear, np.diag(scales), atol=1e-6, rtol=1e-6))
        row["gates"]["original_positive_scale_axes_and_yaw_preserved"] = orientation_ok
        row["accepted"] = all(row["gates"].values())
        if not orientation_ok:
            result["failures"].append(f"{obj['id']}:original_positive_scale_axes_and_yaw_preserved")
    result["accepted"] = not result["failures"]
    result["exact_furniture_object_ids"] = sorted(exported)
    result["p021_physics_evaluated"] = False
    return result


def prepare_scene(spec_path: Path, output: Path, inventory_path: Path, blender: Path) -> dict[str, Any]:
    """Revalidate sources, stage exact bytes, assemble with Blender, and inspect.

    Every attempt gets a fresh output directory. Failure writes a factual
    prepare_result.json and raises; it never manufactures successful geometry.
    """
    spec_path, output, inventory_path, blender = (Path(path).resolve() for path in (spec_path, output, inventory_path, blender))
    require(output != inventory_path.parent and output.is_relative_to(inventory_path.parent),
            "new P021 output must be below the inventory's directory")
    managed = ("prepare_result.json", "scene_request.json", "layout_plan.json", "asset_references.json",
               "asset_resolution.json", "asset_source_policy.json", "layout_qa.json", "scene.glb",
               "geometry_qa.json", "assembly_report.json", "assets")
    require(not any((output / name).exists() for name in managed), "existing preparation evidence is immutable; use a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    result: dict[str, Any] = {"schema": SCHEMA, "status": "incomplete", "ok": False,
                              "output": str(output), "stages": [], "evidence": {}, **REUSE,
                              "physics_evaluated": False, "dynamic_render_evaluated": False,
                              "independent_human_validation": None}
    stage, stage_started = "input_validation", time.perf_counter()

    def finish_stage(name: str) -> None:
        nonlocal stage_started
        result["stages"].append({"stage": name, "ok": True, "wall_seconds": time.perf_counter() - stage_started})
        stage_started = time.perf_counter()

    try:
        spec_binding, inventory_binding = bound(spec_path), bound(inventory_path)
        spec, inventory = read_json(spec_path), read_json(inventory_path)
        selected = validate_spec(spec, inventory)
        require(blender.is_file(), f"Blender binary missing: {blender}")
        result.update(run_id=spec["run_id"], method=spec["method"], development=spec["development"],
                      spec_input=spec_binding, inventory=inventory_binding)
        finish_stage(stage)

        stage = "original_source_and_scoped_review_revalidation"
        rows = [revalidate_asset(entry) for entry in selected]
        finish_stage(stage)

        stage = "new_request_layout_and_source_gates"
        plan = make_plan(spec, rows)
        layout_qa = validate_layout(plan)
        write_json(output / "layout_qa.json", layout_qa)
        require(layout_qa.get("ok") is True, f"new P021 layout rejected: {layout_qa.get('violations')}")
        request = {"schema": "p021-physics-scene-request/v1", "run_id": spec["run_id"],
                   "scene_spec": spec_binding, "scene_spec_hash": content_hash(spec), **REUSE,
                   "prompt": "Arrange the exact referenced bookcase and engineering sofa at the declared metric floor positions. Preserve their reviewed appearances, keep them separated inside the room, and test only exterior floor sliding with an explicitly designed support friction coefficient.",
                   "room": deepcopy(spec["room"]), "objects": deepcopy(spec["objects"]),
                   "asset_refs": [{"object_id": row["case"]["id"], "inventory_id": row["inventory_id"],
                                   "glb": row["asset"], "generation_key": row["generation_key"],
                                   "quality_scope": row["quality_scope"], "prior_quality": row["prior_quality"],
                                   "scoped_admission": row["scoped_admission"]} for row in rows],
                   "relations": [{"type": "supported_by", "source": row["case"]["id"], "target": "floor"} for row in rows],
                   "physical_parameter_origin": spec["parameter_origin"], "measured_asset_friction": None,
                   "material_identity_certified": False, "new_visual_judgment": False,
                   "new_scene_visual_review_required": True, "independent_human_validation": None}
        request["content_key"] = content_hash(request)
        asset_dir = output / "assets"
        resolution = {"mode": "generate", "mode_semantics": "original generation provenance; no generation in P021",
                      "asset_dir": str(asset_dir), "ready_for_assembly": False, **REUSE,
                      "results": [{"object_id": row["case"]["id"], "category": row["case"]["category"],
                                   "status": "generated", **REUSE, "metadata": deepcopy(row["generation"]),
                                   "original_asset": row["asset"], "quality_scope": row["quality_scope"],
                                   "lifecycle": new_lifecycle_record(row["case"]["id"], {
                                       "lifecycle_status": "generated_for_run",
                                       "admission_hash": content_hash(row["scoped_admission"])})} for row in rows]}
        source_gate = audit_asset_source_policy(resolution)
        write_json(output / "asset_source_policy.json", {**source_gate, **REUSE})
        require(source_gate.get("ok") is True, f"P021 generated-source gate rejected: {source_gate.get('failures')}")
        finish_stage(stage)

        stage = "exact_source_staging"
        asset_dir.mkdir()
        for row in rows:
            destination = asset_dir / f"{row['case']['id']}.glb"
            shutil.copyfile(check_binding(row["asset"]), destination)
            require(file_binding(destination) == file_binding(check_binding(row["asset"])), "staging changed original GLB bytes")
            row["staged_asset"] = bound(destination)
        resolution["ready_for_assembly"] = True
        check_binding(spec_binding)
        check_binding(inventory_binding)
        destination_spec = output / "scene_spec.json"
        if destination_spec != spec_path:
            require(not destination_spec.exists() or file_binding(destination_spec) == file_binding(spec_path), "existing output scene specification differs")
            shutil.copyfile(spec_path, destination_spec)
        for name, document in (("scene_request", request), ("layout_plan", plan),
                               ("asset_resolution", resolution), ("asset_references", {"assets": rows, **REUSE})):
            write_json(output / f"{name}.json", document)
        # Bind every assembly input before the subprocess so later mutation is
        # rejected even if the replacement would also pass ordinary QA.
        for name in ("scene_spec", "scene_request", "layout_plan", "asset_resolution", "asset_references", "asset_source_policy", "layout_qa"):
            result["evidence"][name] = bound(output / f"{name}.json")
        for row in rows:
            result["evidence"][f"staged_asset/{row['case']['id']}"] = row["staged_asset"]
        finish_stage(stage)

        stage = "canonical_blender_assembly"
        assembly = runtime.assemble_with_blender(output / "layout_plan.json", asset_dir, output / "scene.glb", blender_bin=blender)
        write_json(output / "assembly_report.json", assembly)
        require(assembly.get("ok") is True, "actual Blender assembly failed")
        finish_stage(stage)

        stage = "final_geometry_correspondence"
        for binding in result["evidence"].values():
            check_binding(binding)
        geometry = inspect_final_scene(output / "scene.glb", plan, rows)
        write_json(output / "geometry_qa.json", geometry)
        require(geometry.get("accepted") is True, f"final geometry rejected: {geometry.get('failures')}")
        # Revalidation is deliberately repeated after Blender for source/image
        # changes during a long assembly; no old source file is ever rewritten.
        current = [revalidate_asset(entry) for entry in selected]
        require(current == [{key: value for key, value in row.items() if key != "staged_asset"} for row in rows],
                "source evidence changed during assembly")
        check_binding(spec_binding)
        check_binding(inventory_binding)
        finish_stage(stage)
        result.update(status="assembled_geometry_verified_physics_pending", ok=True,
                      scene_glb=bound(output / "scene.glb"), object_ids=[obj["id"] for obj in spec["objects"]])
    except Exception as exc:
        result.update(status="rejected", failed_stage=stage, error=f"{type(exc).__name__}: {exc}")
        result["stages"].append({"stage": stage, "ok": False, "wall_seconds": time.perf_counter() - stage_started})
        raise
    finally:
        result["wall_seconds"] = time.perf_counter() - started
        for name in ("assembly_report.json", "geometry_qa.json", "scene.glb", "blender_stdout.txt", "blender_stderr.txt", "layout_qa.json", "asset_source_policy.json"):
            path = output / name
            if path.is_file():
                result["evidence"][name] = bound(path)
        result["content_key"] = content_hash(result)
        write_json(output / "prepare_result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender/blender"))
    args = parser.parse_args(argv)
    result = prepare_scene(args.spec, args.output, args.inventory, args.blender)
    print(json.dumps({"ok": result["ok"], "status": result["status"], "output": result["output"]}, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
