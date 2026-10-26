"""Assemble reviewed P019 assets through the canonical scene runtime.

From the scene repository (CPU preparation, then P007-scheduled Blender work)::

    python -m sage.experiments.codex_trellis_scene_v2.p019_scene_validation prepare
    python -m sage.experiments.codex_trellis_scene_v2.p019_scene_validation run
    python -m sage.experiments.codex_trellis_scene_v2.p019_scene_validation verify

``--root`` is the provider benchmark directory; ``--output`` defaults to its
``scene_validation`` child. Preparation selects the lowest accepted replicate
for every available provider/category, retaining excluded cases in the report.
Each provider gets one room with the same category-specific layout. Both
providers must contribute a reviewed, provenance-valid generated asset.

The caller schedules ``run`` under P007 GPU admission; a fresh canonical CPU/I/O
health gate also runs before each Blender subprocess. No model is invoked here.
Only the existing assembler creates architectural floor/walls. Furnishings are
unmodified copies of reviewed GLBs and remain ``generated_for_run`` assets.

``run`` produces GLBs, actual RGB/depth/instance images, geometry correspondence
QA, and content certificates. Final acceptance additionally requires a genuine
scene visual review at <output>/<provider>/visual_review.json, containing:
reviewer, scene_glb_sha256, content_certificate_hash, content_compliance_passed
and layout_passed (the last two must be true). ``verify`` binds that review to
the exact scene and evidence. Neither preparation nor CPU tests are acceptance.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil
import struct
from typing import Any

import numpy as np

from .asset_admission import new_lifecycle_record
from .asset_source_policy import audit_asset_source_policy
from .content_chain import content_hash, file_binding, make_artifact_certificate, verify_artifact_certificate
from .composition import camera_requirements_from_prompt
from .dimensions import dimension_policy_for_category, resolve_dimension_adaptation
from .p019_provider_benchmark import DEFAULT_ROOT, DIMENSIONS, PROVIDERS, candidate_quality, read_json, write_json
from .resource_health import append_health_checkpoint
from .runtime import assemble_with_blender
from .scene_dna_multiview import VIEW_AXES
from .scene_graph import build_typed_scene_graph, materialize_scene_graph
from .scene_render_acceptance import evaluate_scene_render_manifest, render_and_evaluate_scene
from .validator import validate_layout
from .white_background_real_batch import LOW_UNDER_AXES


SCHEMA = "p019-scene-validation/v1"
# glTF is right-handed Y-up; the scene plan and Blender use right-handed Z-up.
GLTF_TO_Z = np.array([[1., 0., 0., 0.], [0., 0., -1., 0.], [0., 1., 0., 0.], [0., 0., 0., 1.]])
POSES = {"sofa": (1.65, 3.35), "bookcase": (4.15, 3.70), "storage_box": (3.75, 2.50)}


def require(condition: Any, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def bound(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), **file_binding(path)}


def check_binding(record: dict[str, Any]) -> Path:
    path = Path(record["path"])
    require(file_binding(path) == {key: record[key] for key in ("bytes", "sha256")}, f"file content changed: {path}")
    return path


def sealed_key(document: dict[str, Any], key: str = "content_key") -> None:
    require(document.get(key) == content_hash({name: value for name, value in document.items() if name != key}), f"invalid {key}")


def verify_audit(root: Path, frozen: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Revalidate current files, not the benchmark's cached accepted boolean."""
    directory = root / "cases" / case["id"]
    audit = read_json(directory / "audit.json")
    require(audit.get("schema") == "p019-case-audit/v1" and audit.get("status") == "accepted", "asset is not visually accepted")
    for name in ("accepted", "automated_accepted", "source_policy_ok", "glb_ok", "hard_geometry_gate_passed", "visual_review_binding_ok", "visual_review_passed", "frozen_three_d_control_passed"):
        require(audit.get(name) is True, f"asset audit rejected: {name}")
    require(audit.get("case_id") == case["id"] and audit.get("provider") == case["provider"], "audit case/provider mismatch")
    glb = Path(audit["glb_path"])
    generation = read_json(directory / "generation.json")
    contract = read_json(directory / "generation_contract.json")
    sealed_key(contract)
    require(contract == generation.get("generation_contract"), "generation contract mismatch")
    require(contract["content_key"] == audit.get("generation_key") == generation.get("generation_key"), "generation key mismatch")
    require(contract.get("case_id") == case["id"] and contract.get("frozen_cases_key") == frozen["content_key"], "frozen case contract mismatch")
    require(contract.get("target_dimensions_m") == case["dimensions"] and contract.get("image_provider") == case["provider"], "generation specification mismatch")
    result = read_json(directory / "trellis" / "result.json")
    require(result.get("ok") is True and result.get("status") == "generated", "TRELLIS result not successful")
    require(file_binding(glb) == result.get("glb_binding") and file_binding(glb)["sha256"] == audit.get("glb_sha256"), "reviewed GLB content changed")
    metadata = read_json(directory / "trellis" / "bridge_metadata.json")
    require(metadata == generation.get("bridge_metadata") and content_hash(metadata) == contract.get("bridge_metadata_hash"), "bridge metadata changed")
    require(metadata.get("job_id") == contract.get("trellis_job_id") == result.get("job_id") == generation.get("job_id"), "TRELLIS job mismatch")
    request = read_json(directory / "trellis" / "request.json")
    require(content_hash(request["payload"]) == request.get("request_hash") == contract.get("generation_request_hash"), "promotion request hash mismatch")
    require(request["payload"] == generation.get("request"), "promotion payload mismatch")
    candidate = read_json(directory / "candidate" / "bridge_metadata.json")
    quality = candidate_quality(candidate, case, contract["candidate_job_id"])
    require(quality["ok"], f"candidate evidence rejected: {quality.get('failures')}")
    require(file_binding(Path(quality["source_rgb"]["path"])) == contract.get("reference_image"), "candidate source changed")
    source = audit_asset_source_policy({"mode": "generate", "results": [{"object_id": case["id"], "category": case["category"], "status": "generated", "metadata": generation}]})
    require(source["ok"], f"generated source policy rejected: {source.get('failures')}")
    visual = read_json(directory / "visual_review.json")
    require(visual.get("reviewer") and visual.get("generation_key") == contract["content_key"] and visual.get("glb_sha256") == audit["glb_sha256"], "asset visual review binding changed")
    require(visual.get("requirement_compliance_passed") is True and visual.get("geometry_multiview_passed") is True, "asset visual review failed")
    require(set(audit["standard_views"]) == set(VIEW_AXES) and set(audit["low_under_views"]) == set(LOW_UNDER_AXES), "required 4+8 views missing")
    evidence = {f"standard_{axis}": Path(path) for axis, path in audit["standard_views"].items()}
    evidence.update({f"low_under_{axis}": Path(path) for axis, path in audit["low_under_views"].items()})
    evidence.update(bridge_metadata=directory / "trellis" / "bridge_metadata.json", source_policy=directory / "source_policy_report.json", standard_report=Path(audit["standard_qa_path"]), low_under_report=Path(audit["low_under_qa_path"]))
    for name in ("standard_contact_sheet", "low_under_contact_sheet"):
        if audit.get(name):
            evidence[name] = Path(audit[name])
    certificate = read_json(directory / "audit_certificate.json")
    rules = certificate.get("rules", {})
    require(rules.get("schema") == "p019-asset-audit/v1" and rules.get("standard_axes") == list(VIEW_AXES) and rules.get("low_under_axes") == list(LOW_UNDER_AXES), "unexpected asset audit rules")
    ok, reasons = verify_artifact_certificate(certificate, glb, upstream={"generation_contract": contract, "generation_key": contract["content_key"]}, rules=rules, evidence=evidence)
    require(ok, f"asset audit certificate changed: {reasons}")
    standard = read_json(Path(audit["standard_qa_path"]))
    low = read_json(Path(audit["low_under_qa_path"]))
    require(standard.get("hard_geometry_gate_passed") is True and low.get("ok") is True, "multiview geometry rejected")
    evidence.update(audit=directory / "audit.json", audit_certificate=directory / "audit_certificate.json", visual_review=directory / "visual_review.json", generation=directory / "generation.json", generation_contract=directory / "generation_contract.json", asset_object=directory / "asset_object.json", candidate_metadata=directory / "candidate" / "bridge_metadata.json", trellis_request=directory / "trellis" / "request.json", trellis_result=directory / "trellis" / "result.json")
    return {"case": deepcopy(case), "asset": bound(glb), "generation_key": contract["content_key"], "generation": generation, "source_policy": source, "evidence": {name: bound(path) for name, path in evidence.items()}}


def make_plan(rows: list[dict[str, Any]], provider: str) -> dict[str, Any]:
    objects = []
    for row in rows:
        case = row["case"]
        obj = read_json(check_binding(row["evidence"]["asset_object"]))
        require(obj["id"] == case["id"] and obj["dimensions"] == case["dimensions"], "audited object mismatch")
        # Preserve the orientation actually used for the accepted 4+8 captures.
        require(obj.get("asset_axis_to_z", 2) == 2 and not obj.get("asset_local_yaw_offset_degrees", 0), "unsupported changed audited orientation")
        policy = dimension_policy_for_category(case["category"])
        obj.update(x=POSES[case["category"]][0], y=POSES[case["category"]][1], z=0.0, yaw=0.0,
                   required=True, placement_type="floor", provenance="p019_acceptance_request",
                   asset_source="generated", image_provider=provider, asset_glb_sha256=row["asset"]["sha256"],
                   dimension_policy=policy, dimension_resolution=resolve_dimension_adaptation(None, case["dimensions"], policy))
        objects.append(obj)
    by_category = {obj["category"]: obj["id"] for obj in objects}
    relations = []
    for left, relation, right in (("sofa", "left_of", "bookcase"), ("storage_box", "in_front_of", "bookcase")):
        if left in by_category and right in by_category:
            relations.append({"type": relation, "source": by_category[left], "target": by_category[right], "strength": "hard", "reference_frame": "room", "provenance": "p019_acceptance_request"})
    plan = {"schema": "codex_trellis_scene_plan_v2", "room_type": "living_room", "room": {"width": 5.5, "length": 4.8, "height": 2.8},
            "architecture": {"walls": ["north", "south", "east", "west"], "doors": [], "windows": [], "requirements": {"door_count": 0},
                             "floor": {"id": "floor", "material": {"material_id": "warm_gray", "texture_type": "procedural_tile", "base_color": [0.72, 0.70, 0.66]}},
                             "wall_finish": {"default": {"material_id": "neutral_plaster", "texture_type": "procedural_painted_plaster", "base_color": [0.89, 0.885, 0.855]}}},
            "objects": objects, "relations": relations, "camera_requirements": {**camera_requirements_from_prompt(""), "complete_required_objects_visible": True},
            "object_budget": {"hard_min": len(objects), "target_max": len(objects), "hard_runtime_limit": len(objects), "required_object_ids": [obj["id"] for obj in objects]},
            "p019_provider": provider, "scene_purpose": "generated_asset_in_scene_acceptance"}
    plan["scene_graph"] = materialize_scene_graph(build_typed_scene_graph(plan), objects)
    return plan


def prepare(root: Path, output: Path) -> dict[str, Any]:
    frozen = read_json(root / "frozen_cases.json")
    sealed_key(frozen)
    require(content_hash(read_json(root / "frozen_plan.json")) == frozen["preregistration_hash"], "preregistration changed")
    if (output / "prepared.json").exists():
        return verify_prepared(root, output)
    accepted, excluded = [], []
    for case in frozen["cases"]:
        try:
            accepted.append(verify_audit(root, frozen, case))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            excluded.append({"case_id": case["id"], "reason": f"{type(exc).__name__}: {exc}"})
    selected = {}
    for row in sorted(accepted, key=lambda item: (item["case"]["replicate"], item["case"]["id"])):
        selected.setdefault((row["case"]["provider"], row["case"]["category"]), row)
    rows = [selected[key] for key in sorted(selected)]
    coverage = {provider: [row["case"]["category"] for row in rows if row["case"]["provider"] == provider] for provider in PROVIDERS}
    write_json(output / "selection_report.json", {"selection_policy": "lowest accepted replicate in each available provider/category", "coverage": coverage, "excluded": excluded, "all_valid_accepted_ids": [row["case"]["id"] for row in accepted]})
    require(all(coverage.values()), "both providers must have at least one currently valid visually accepted asset; see selection_report.json")
    scenes, files = {}, {"selection_report": bound(output / "selection_report.json"), "frozen_cases": bound(root / "frozen_cases.json"), "frozen_plan": bound(root / "frozen_plan.json")}
    for provider in PROVIDERS:
        provider_rows = [row for row in rows if row["case"]["provider"] == provider]
        directory = output / provider
        asset_dir = directory / "assets"
        asset_dir.mkdir(parents=True, exist_ok=True)
        for row in provider_rows:
            destination = asset_dir / f"{row['case']['id']}.glb"
            shutil.copyfile(check_binding(row["asset"]), destination)
            row["staged_asset"] = bound(destination)
            require(file_binding(destination) == file_binding(Path(row["asset"]["path"])), "staged asset hash mismatch")
        plan = make_plan(provider_rows, provider)
        layout_qa = validate_layout(plan)
        write_json(directory / "layout_qa.json", layout_qa)
        require(layout_qa["ok"], f"layout rejected: {layout_qa['violations']}")
        request = {"schema": "p019-scene-request/v1", "provider": provider, "prompt": "Arrange the referenced reviewed assets in a room. Place the sofa left of the bookcase and the storage box in front of the bookcase when present. Keep every asset supported on the floor, separated, and completely visible in at least one real camera view.", "asset_refs": [{"object_id": row["case"]["id"], "category": row["case"]["category"], "glb": row["asset"], "generation_key": row["generation_key"]} for row in provider_rows], "relations": plan["relations"], "room": plan["room"]}
        resolution = {"mode": "generate", "asset_dir": str(asset_dir), "ready_for_assembly": True, "results": [{"object_id": row["case"]["id"], "category": row["case"]["category"], "status": "generated", "metadata": row["generation"], "lifecycle": new_lifecycle_record(row["case"]["id"], {"lifecycle_status": "generated_for_run", "admission_hash": row["evidence"]["audit_certificate"]["sha256"]})} for row in provider_rows]}
        source_gate = audit_asset_source_policy(resolution)
        require(source_gate["ok"], "assembled generated source gate rejected")
        for name, value in (("scene_request", request), ("layout_plan", plan), ("asset_resolution", resolution), ("asset_source_policy", source_gate), ("asset_references", {"assets": provider_rows})):
            write_json(directory / f"{name}.json", value)
            files[f"{provider}/{name}"] = bound(directory / f"{name}.json")
        files[f"{provider}/layout_qa"] = bound(directory / "layout_qa.json")
        scenes[provider] = {"directory": str(directory), "object_ids": [row["case"]["id"] for row in provider_rows]}
    prepared = {"schema": SCHEMA, "status": "prepared_not_rendered", "root": str(root), "output": str(output), "coverage": coverage, "scenes": scenes, "files": files}
    prepared["content_key"] = content_hash(prepared)
    write_json(output / "prepared.json", prepared)
    return prepared


def verify_prepared(root: Path, output: Path) -> dict[str, Any]:
    prepared = read_json(output / "prepared.json")
    sealed_key(prepared)
    require(prepared.get("root") == str(root) and prepared.get("output") == str(output), "preparation directory mismatch")
    for binding in prepared["files"].values():
        check_binding(binding)
    frozen = read_json(root / "frozen_cases.json")
    for provider in PROVIDERS:
        rows = read_json(output / provider / "asset_references.json")["assets"]
        require(rows and all(row["case"]["provider"] == provider for row in rows), "provider scene coverage missing")
        for row in rows:
            check_binding(row["asset"])
            check_binding(row["staged_asset"])
            for binding in row["evidence"].values():
                check_binding(binding)
            current = verify_audit(root, frozen, row["case"])
            require(current == {key: value for key, value in row.items() if key != "staged_asset"}, "asset audit changed after scene preparation")
    return prepared


def glb_document(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    require(len(data) >= 20 and data[:4] == b"glTF", f"invalid GLB: {path}")
    _, version, total = struct.unpack_from("<4sII", data)
    require(version == 2 and total == len(data), "invalid GLB length/version")
    offset, document, binary = 12, None, b""
    while offset < len(data):
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        chunk = data[offset:offset + size]
        require(len(chunk) == size, "truncated GLB chunk")
        if kind == 0x4E4F534A:
            document = json.loads(chunk)
        elif kind == 0x004E4942:
            binary = chunk
        offset += size
    require(isinstance(document, dict), "GLB JSON missing")
    return document, binary


def local_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=float).reshape(4, 4).T
    from scipy.spatial.transform import Rotation
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(node.get("rotation", [0, 0, 0, 1])).as_matrix() @ np.diag(node.get("scale", [1, 1, 1]))
    result[:3, 3] = node.get("translation", [0, 0, 0])
    require(np.isfinite(result).all(), "nonfinite GLB node transform")
    return result


def world_matrices(document: dict[str, Any]) -> dict[int, np.ndarray]:
    result = {}
    nodes = document.get("nodes", [])
    def visit(index: int, parent: np.ndarray) -> None:
        require(index not in result, "GLB node cycle or multiple parents")
        result[index] = parent @ local_matrix(nodes[index])
        for child in nodes[index].get("children", []):
            visit(child, result[index])
    for index in document["scenes"][document.get("scene", 0)]["nodes"]:
        visit(index, np.eye(4))
    return result


def positions(document: dict[str, Any], binary: bytes, accessor_index: int) -> np.ndarray:
    accessor = document["accessors"][accessor_index]
    require(accessor.get("componentType") == 5126 and accessor.get("type") == "VEC3" and "sparse" not in accessor, "unsupported POSITION accessor")
    view = document["bufferViews"][accessor["bufferView"]]
    require(view.get("buffer", 0) == 0, "external GLB position buffer")
    return np.ndarray((accessor["count"], 3), dtype="<f4", buffer=binary, offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0), strides=(view.get("byteStride", 12), 4)).astype(float)


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    return points @ matrix[:3, :3].T + matrix[:3, 3]


def node_geometry(document: dict[str, Any], binary: bytes, index: int, matrix: np.ndarray) -> tuple[np.ndarray, int]:
    clouds, faces = [], 0
    mesh = document["meshes"][document["nodes"][index]["mesh"]]
    for primitive in mesh["primitives"]:
        require(primitive.get("mode", 4) == 4, "non-triangle GLB primitive")
        cloud = positions(document, binary, primitive["attributes"]["POSITION"])
        clouds.append(transform_points(cloud, matrix))
        faces += (document["accessors"][primitive["indices"]]["count"] if "indices" in primitive else len(cloud)) // 3
    return np.concatenate(clouds), faces


def inspect_scene(scene_glb: Path, plan: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Recover exported transforms and compare every asset's real vertex cloud.

    The symmetric nearest-vertex distance allows Blender's UV seam splitting;
    triangle counts and transformed geometry must still match the input GLB.
    Disjoint world AABBs prove furniture pairs cannot intersect in this layout.
    """
    from scipy.spatial import cKDTree
    document, binary = glb_document(scene_glb)
    worlds = world_matrices(document)
    objects, failures = {}, []
    by_id = {row["case"]["id"]: row for row in rows}
    for obj in plan["objects"]:
        identifier = obj["id"]
        indices = [index for index in worlds if document["nodes"][index].get("extras", {}).get("scene_object_id") == identifier]
        roots = [index for index in indices if document["nodes"][index].get("name") == f"{identifier}_root"]
        meshes = [index for index in indices if "mesh" in document["nodes"][index]]
        require(len(roots) == 1 and meshes, f"exported object/root missing: {identifier}")
        root_matrix = worlds[roots[0]]
        asset_to_world = GLTF_TO_Z @ root_matrix
        actual_parts = [node_geometry(document, binary, index, GLTF_TO_Z @ worlds[index]) for index in meshes]
        actual = np.concatenate([part[0] for part in actual_parts])
        source_document, source_binary = glb_document(check_binding(by_id[identifier]["staged_asset"]))
        source_worlds = world_matrices(source_document)
        expected_parts = [node_geometry(source_document, source_binary, index, asset_to_world @ matrix) for index, matrix in source_worlds.items() if "mesh" in source_document["nodes"][index]]
        expected = np.concatenate([part[0] for part in expected_parts])
        require(np.isfinite(actual).all() and np.isfinite(expected).all(), "nonfinite exported geometry")
        discrepancy = max(float(cKDTree(expected).query(actual)[0].max()), float(cKDTree(actual).query(expected)[0].max()))
        bounds = np.asarray([actual.min(axis=0), actual.max(axis=0)])
        target = np.asarray([obj["dimensions"][axis] for axis in ("width", "length", "height")])
        expected_center = np.asarray([obj["x"], obj["y"], obj["z"] + target[2] / 2])
        gates = {"geometry_matches_reviewed_glb": discrepancy <= 1e-4,
                 "triangle_count_preserved": sum(part[1] for part in actual_parts) == sum(part[1] for part in expected_parts),
                 "dimensions_match_request": bool(np.allclose(bounds[1] - bounds[0], target, atol=0.002, rtol=0.002)),
                 "world_placement_matches_layout": bool(np.allclose(bounds.mean(axis=0), expected_center, atol=0.002, rtol=0)),
                 "supported_by_floor": abs(float(bounds[0, 2])) <= 0.002,
                 "inside_room": bool(bounds[0, 0] >= 0 and bounds[0, 1] >= 0 and bounds[1, 0] <= plan["room"]["width"] and bounds[1, 1] <= plan["room"]["length"] and bounds[1, 2] <= plan["room"]["height"])}
        objects[identifier] = {"source_glb": by_id[identifier]["asset"], "generation_key": by_id[identifier]["generation_key"],
                               "root_world_matrix_gltf_y_up": root_matrix.tolist(), "asset_gltf_to_scene_z_up_matrix": asset_to_world.tolist(),
                               "world_bounds_z_up_m": bounds.tolist(), "mesh_world_matrices_z_up": {document["nodes"][index]["name"]: (GLTF_TO_Z @ worlds[index]).tolist() for index in meshes},
                               "actual_triangle_count": sum(part[1] for part in actual_parts), "source_triangle_count": sum(part[1] for part in expected_parts),
                               "symmetric_vertex_distance_m": discrepancy, "gates": gates, "accepted": all(gates.values())}
        failures.extend(f"{identifier}:{name}" for name, ok in gates.items() if not ok)
    pairs = []
    identifiers = list(objects)
    for offset, left in enumerate(identifiers):
        for right in identifiers[offset + 1:]:
            a, b = np.asarray(objects[left]["world_bounds_z_up_m"]), np.asarray(objects[right]["world_bounds_z_up_m"])
            overlap = np.minimum(a[1], b[1]) - np.maximum(a[0], b[0])
            separated = bool(np.any(overlap < -0.002))
            pairs.append({"source": left, "target": right, "disjoint_world_aabb": separated, "axis_overlap_m": overlap.tolist()})
            if not separated:
                failures.append(f"possible_furniture_intersection:{left}:{right}")
    for relation in plan["relations"]:
        a, b = np.asarray(objects[relation["source"]]["world_bounds_z_up_m"]), np.asarray(objects[relation["target"]]["world_bounds_z_up_m"])
        ok = a[1, 0] < b[0, 0] if relation["type"] == "left_of" else a[1, 1] < b[0, 1]
        if not ok:
            failures.append(f"actual_relation_failed:{relation['source']}:{relation['type']}:{relation['target']}")
    return {"schema": "p019-scene-geometry-correspondence/v1", "scene_glb": bound(scene_glb), "objects": objects, "pairs": pairs, "accepted": not failures, "failures": failures,
            "coordinate_contract": "Matrices use column vectors. asset_gltf_to_scene_z_up maps original GLB world coordinates into the assembled room's Z-up metre coordinates; each original GLB node world matrix precedes it.",
            "limitations": ["Floor support measures mesh bottom distance; this is not dynamic stability or P021 physics.", "Geometry correspondence compares vertex locations and triangle counts, not texture appearance; real renders require separate visual review."]}


def scene_evidence(directory: Path) -> dict[str, Path]:
    evidence = {name: directory / filename for name, filename in (("plan", "layout_plan.json"), ("request", "scene_request.json"), ("asset_references", "asset_references.json"), ("source_policy", "asset_source_policy.json"), ("layout_qa", "layout_qa.json"), ("assembly", "assembly_report.json"), ("geometry", "geometry_qa.json"), ("render_qa", "renders/scene_render_acceptance_report.json"), ("render_manifest", "renders/render_manifest.json"), ("preview", "scene_front_45.png"), ("preview_center", "scene_front_center_45.png"))}
    for path in sorted((directory / "renders").rglob("*.png")):
        evidence[f"render/{path.relative_to(directory / 'renders')}"] = path
    # Enumerate the manifest references as well; absent masks can legitimately
    # use a shared object-index image, which is still a required bound artifact.
    manifest = read_json(evidence["render_manifest"])
    for view, row in manifest.get("qa_passes", {}).get("views", {}).items():
        for key in ("rgb_path", "depth_path", "object_index_path"):
            if row.get(key):
                evidence[f"manifest/{view}/{key}"] = Path(row[key])
        for identifier, obj in row.get("objects", {}).items():
            for key in ("mask_path", "object_index_path"):
                if obj.get(key) and Path(obj[key]).is_file():
                    evidence[f"manifest/{view}/{identifier}/{key}"] = Path(obj[key])
    return evidence


def run(root: Path, output: Path, blender: Path, resolution: int, provider: str | None = None) -> dict[str, Any]:
    prepared = verify_prepared(root, output)
    require(blender.is_file(), f"Blender missing: {blender}")
    for selected_provider in ([provider] if provider else list(PROVIDERS)):
        directory = output / selected_provider
        if (directory / "scene_certificate.json").exists():
            # Completed captures are immutable. Verify them instead of quietly
            # replacing scene bytes already inspected by a reviewer.
            verify_scene(root, output, selected_provider)
            continue
        plan_path = directory / "layout_plan.json"
        scene_glb = directory / "scene.glb"
        append_health_checkpoint(output / "resource_health.jsonl", stage=f"p019_assemble:{selected_provider}", require_healthy=True)
        assembly = assemble_with_blender(plan_path, directory / "assets", scene_glb, blender_bin=blender, preview_image=directory / "scene_front_45.png", preview_image_center=directory / "scene_front_center_45.png")
        write_json(directory / "assembly_report.json", assembly)
        plan = read_json(plan_path)
        rows = read_json(directory / "asset_references.json")["assets"]
        geometry = inspect_scene(scene_glb, plan, rows)
        write_json(directory / "geometry_qa.json", geometry)
        append_health_checkpoint(output / "resource_health.jsonl", stage=f"p019_render:{selected_provider}", require_healthy=True)
        render = render_and_evaluate_scene(blender_bin=blender, scene_glb=scene_glb, plan_path=plan_path, asset_dir=directory / "assets", output_dir=directory / "renders", resolution=resolution)
        require(render.get("evaluated"), f"scene rendering failed: {directory / 'renders'}")
        verify_prepared(root, output)
        rules = {"schema": SCHEMA, "resolution": resolution, "harness": bound(Path(__file__)), "blender": bound(blender),
                 "assembler": bound(Path(__file__).resolve().parents[2] / "scripts" / "blender_assemble_sage_scene.py"), "renderer": bound(Path(__file__).resolve().parents[2] / "scripts" / "blender_render_sage_diagnostics.py")}
        certificate = make_artifact_certificate(scene_glb, upstream={"prepared_content_key": prepared["content_key"], "provider": selected_provider}, rules=rules, evidence=scene_evidence(directory))
        write_json(directory / "scene_certificate.json", certificate)
        automated = bool(assembly.get("ok") and geometry["accepted"] and render.get("accepted"))
        write_json(directory / "render_result.json", {"automated_accepted": automated, "status": "scene_visual_review_required" if automated else "scene_qa_rejected", "scene_glb": bound(scene_glb), "content_certificate_hash": certificate["certificate_hash"]})
    return verify(root, output)


def verify_scene(root: Path, output: Path, provider: str) -> dict[str, Any]:
    prepared = verify_prepared(root, output)
    directory = output / provider
    scene_glb = directory / "scene.glb"
    certificate = read_json(directory / "scene_certificate.json")
    require(certificate.get("rules", {}).get("schema") == SCHEMA, "scene certificate schema mismatch")
    for key in ("harness", "blender", "assembler", "renderer"):
        check_binding(certificate["rules"][key])
    ok, reasons = verify_artifact_certificate(certificate, scene_glb, upstream={"prepared_content_key": prepared["content_key"], "provider": provider}, rules=certificate["rules"], evidence=scene_evidence(directory))
    require(ok, f"scene evidence changed: {reasons}")
    render = evaluate_scene_render_manifest(read_json(directory / "renders" / "render_manifest.json"), read_json(directory / "layout_plan.json"))
    geometry = read_json(directory / "geometry_qa.json")
    automated = bool(render["accepted"] and geometry["accepted"] and read_json(directory / "assembly_report.json").get("ok"))
    review_path = directory / "visual_review.json"
    review = read_json(review_path) if review_path.is_file() else {}
    review_bound = bool(review.get("reviewer") and review.get("scene_glb_sha256") == file_binding(scene_glb)["sha256"] and review.get("content_certificate_hash") == certificate["certificate_hash"])
    review_ok = bool(review_bound and review.get("content_compliance_passed") is True and review.get("layout_passed") is True)
    return {"provider": provider, "automated_accepted": automated, "accepted": automated and review_ok, "status": "accepted" if automated and review_ok else ("scene_visual_review_required" if automated and not review else "rejected"), "scene_glb": bound(scene_glb), "content_certificate_hash": certificate["certificate_hash"], "visual_review_binding_ok": review_bound, "visual_review": bound(review_path) if review else None, "render_images": {key: str(path) for key, path in scene_evidence(directory).items() if path.suffix == ".png"}, "geometry_qa": str(directory / "geometry_qa.json"), "render_qa": str(directory / "renders" / "scene_render_acceptance_report.json")}


def verify(root: Path, output: Path) -> dict[str, Any]:
    prepared = verify_prepared(root, output)
    scenes = {}
    for provider in PROVIDERS:
        try:
            scenes[provider] = verify_scene(root, output, provider)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            scenes[provider] = {"provider": provider, "accepted": False, "automated_accepted": False, "status": "incomplete_or_invalid", "error": f"{type(exc).__name__}: {exc}"}
    report = {"schema": SCHEMA, "accepted": all(row["accepted"] for row in scenes.values()), "automated_accepted": all(row["automated_accepted"] for row in scenes.values()), "coverage": prepared["coverage"], "prepared_content_key": prepared["content_key"], "scenes": scenes, "auto_curated": False, "p021_physics_evaluated": False}
    write_json(output / "scene_validation_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "run", "verify"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--blender", type=Path, default=Path("/data/wsj/tools/blender/blender"))
    parser.add_argument("--resolution", type=int, default=512)
    parser.add_argument("--provider", choices=PROVIDERS, help="Run one provider at a time under the caller's P007 schedule")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "scene_validation"
    require(128 <= args.resolution <= 2048, "resolution must be 128..2048")
    if args.command == "prepare":
        report = prepare(root, output)
    elif args.command == "run":
        report = run(root, output, args.blender.resolve(), args.resolution, args.provider)
    else:
        report = verify(root, output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    completed_run = args.command == "run" and (
        report.get("scenes", {}).get(args.provider, {}).get("automated_accepted")
        if args.provider else report.get("automated_accepted")
    )
    return 0 if args.command == "prepare" or report.get("accepted") or completed_run else 2


if __name__ == "__main__":
    raise SystemExit(main())
