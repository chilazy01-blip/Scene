"""CPU contract tests only; synthetic tetrahedra are not scene assets."""

from copy import deepcopy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .. import p019_scene_validation as harness
from ..content_chain import content_hash, file_binding, make_artifact_certificate
from ..white_background_real_batch import _object


def tetrahedron_glb(path, *, root=None, object_id=None, offset=0.0):
    """A four-face mathematical fixture for coordinate/identity checks."""
    vertices = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype="<f4")
    vertices[:, 0] += offset
    indices = np.asarray([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3], dtype="<u2")
    binary = vertices.tobytes() + indices.tobytes()
    node = {"name": "fixture_geometry", "mesh": 0}
    nodes, scene_nodes = [node], [0]
    if object_id:
        node.update(name=f"{object_id}_geometry_000_fixture", extras={"scene_object_id": object_id})
        nodes.append({"name": f"{object_id}_root", "matrix": np.asarray(root).T.reshape(-1).tolist(), "children": [0], "extras": {"scene_object_id": object_id}})
        scene_nodes = [1]
    document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": scene_nodes}], "nodes": nodes,
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
                "buffers": [{"byteLength": len(binary)}], "bufferViews": [{"buffer": 0, "byteLength": vertices.nbytes}, {"buffer": 0, "byteOffset": vertices.nbytes, "byteLength": indices.nbytes}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"}, {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"}]}
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    binary += b"\0" * (-len(binary) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(body) + len(binary)) + struct.pack("<II", len(body), 0x4E4F534A) + body + struct.pack("<II", len(binary), 0x004E4942) + binary)


class P019SceneValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_real_export_matrix_maps_original_gltf_vertices_to_room_z_up(self):
        source, scene = self.root / "source.glb", self.root / "scene.glb"
        tetrahedron_glb(source)
        matrix = np.eye(4)
        matrix[:3, 3] = [1.5, 0, -3.5]
        tetrahedron_glb(scene, root=matrix, object_id="fixture")
        plan = {"objects": [{"id": "fixture", "x": 2, "y": 3, "z": 0, "dimensions": {"width": 1, "length": 1, "height": 1}}], "room": {"width": 5, "length": 5, "height": 3}, "relations": []}
        rows = [{"case": {"id": "fixture"}, "asset": harness.bound(source), "staged_asset": harness.bound(source), "generation_key": "test-only"}]
        result = harness.inspect_scene(scene, plan, rows)
        self.assertTrue(result["accepted"], result)
        np.testing.assert_allclose(result["objects"]["fixture"]["world_bounds_z_up_m"], [[1.5, 2.5, 0], [2.5, 3.5, 1]])
        self.assertEqual(result["objects"]["fixture"]["source_triangle_count"], 4)
        tetrahedron_glb(scene, root=matrix, object_id="fixture", offset=0.03)
        changed = harness.inspect_scene(scene, plan, rows)
        self.assertFalse(changed["accepted"])
        self.assertIn("fixture:geometry_matches_reviewed_glb", changed["failures"])

    def test_world_transform_rejects_cycle_and_bad_glb(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            harness.world_matrices({"scenes": [{"nodes": [0]}], "nodes": [{"children": [0]}]})
        path = self.root / "invalid.glb"
        path.write_bytes(b"glTF incomplete")
        with self.assertRaises(ValueError):
            harness.glb_document(path)

    def test_all_category_layout_has_floor_relations_and_canonical_gates(self):
        rows = []
        for category, dimensions in harness.DIMENSIONS.items():
            case = {"id": category, "category": category, "dimensions": dimensions, "prompt": f"test-only {category}"}
            object_path = self.root / f"{category}.json"
            harness.write_json(object_path, _object(case))
            rows.append({"case": case, "asset": {"sha256": "test-only"}, "evidence": {"asset_object": harness.bound(object_path)}})
        plan = harness.make_plan(rows, "builtin_imagegen")
        result = harness.validate_layout(plan)
        self.assertTrue(result["ok"], result["violations"])
        floor_relations = [edge for edge in plan["scene_graph"]["relations"] if edge["type"] == "supported_by" and edge["target"] == "floor"]
        self.assertEqual(len(floor_relations), 3)
        self.assertTrue(all(obj["asset_source"] == "generated" for obj in plan["objects"]))
        self.assertTrue(all(obj["dimension_resolution"]["requires_runtime_bounds_check"] for obj in plan["objects"]))

    def audit_fixture(self):
        case = {"id": "storage_box__builtin_imagegen__r1", "category": "storage_box", "provider": "builtin_imagegen", "replicate": 1, "dimensions": harness.DIMENSIONS["storage_box"], "prompt": "test-only"}
        frozen = {"content_key": "test-only-frozen", "cases": [case]}
        directory = self.root / "cases" / case["id"]
        directory.mkdir(parents=True)
        glb, image = directory / "fixture.glb", directory / "fixture.png"
        tetrahedron_glb(glb)
        image.write_bytes(b"test-only image; no real render claim")
        request = {"payload": {"image_provider": case["provider"]}}
        request["request_hash"] = content_hash(request["payload"])
        metadata = {"job_id": "trellis-test-job"}
        contract = {"case_id": case["id"], "frozen_cases_key": frozen["content_key"], "target_dimensions_m": case["dimensions"], "image_provider": case["provider"], "bridge_metadata_hash": content_hash(metadata), "trellis_job_id": metadata["job_id"], "candidate_job_id": "candidate-test-job", "generation_request_hash": request["request_hash"], "reference_image": file_binding(image)}
        contract["content_key"] = content_hash(contract)
        generation = {"job_id": metadata["job_id"], "request": request["payload"], "bridge_metadata": metadata, "generation_contract": contract, "generation_key": contract["content_key"]}
        documents = {"generation.json": generation, "generation_contract.json": contract, "asset_object.json": _object(case), "trellis/result.json": {"ok": True, "status": "generated", "job_id": metadata["job_id"], "glb_binding": file_binding(glb)}, "trellis/bridge_metadata.json": metadata, "trellis/request.json": request, "candidate/bridge_metadata.json": {}, "visual_review.json": {"reviewer": "test fixture", "generation_key": contract["content_key"], "glb_sha256": file_binding(glb)["sha256"], "requirement_compliance_passed": True, "geometry_multiview_passed": True}, "source_policy_report.json": {"ok": True}, "standard.json": {"hard_geometry_gate_passed": True}, "low.json": {"ok": True}}
        for name, value in documents.items():
            harness.write_json(directory / name, value)
        audit = {"schema": "p019-case-audit/v1", "status": "accepted", "case_id": case["id"], "provider": case["provider"], "glb_path": str(glb), "glb_sha256": file_binding(glb)["sha256"], "generation_key": contract["content_key"], "standard_views": {axis: str(image) for axis in harness.VIEW_AXES}, "low_under_views": {axis: str(image) for axis in harness.LOW_UNDER_AXES}, "standard_qa_path": str(directory / "standard.json"), "low_under_qa_path": str(directory / "low.json")}
        audit.update({key: True for key in ("accepted", "automated_accepted", "source_policy_ok", "glb_ok", "hard_geometry_gate_passed", "visual_review_binding_ok", "visual_review_passed", "frozen_three_d_control_passed")})
        evidence = {f"standard_{axis}": image for axis in harness.VIEW_AXES}
        evidence.update({f"low_under_{axis}": image for axis in harness.LOW_UNDER_AXES})
        evidence.update(bridge_metadata=directory / "trellis/bridge_metadata.json", source_policy=directory / "source_policy_report.json", standard_report=directory / "standard.json", low_under_report=directory / "low.json")
        certificate = make_artifact_certificate(glb, upstream={"generation_contract": contract, "generation_key": contract["content_key"]}, rules={"schema": "p019-asset-audit/v1", "resolution": 128, "standard_axes": list(harness.VIEW_AXES), "low_under_axes": list(harness.LOW_UNDER_AXES)}, evidence=evidence)
        harness.write_json(directory / "audit_certificate.json", certificate)
        harness.write_json(directory / "audit.json", audit)
        return frozen, case, directory, image

    def test_audit_rechecks_generated_source_gate_and_image_certificate(self):
        frozen, case, directory, image = self.audit_fixture()
        candidate = {"ok": True, "source_rgb": harness.bound(image)}
        with patch.object(harness, "candidate_quality", return_value=candidate), patch.object(harness, "audit_asset_source_policy", return_value={"ok": True}) as source_gate:
            row = harness.verify_audit(self.root, frozen, case)
            self.assertEqual(row["case"]["id"], case["id"])
            self.assertEqual(source_gate.call_args.args[0]["results"][0]["status"], "generated")
            image.write_bytes(b"changed diagnostic evidence")
            with self.assertRaises(ValueError):
                harness.verify_audit(self.root, frozen, case)
        image.write_bytes(b"test-only image; no real render claim")
        with patch.object(harness, "candidate_quality", return_value=candidate), patch.object(harness, "audit_asset_source_policy", return_value={"ok": False, "failures": ["forged source"]}):
            with self.assertRaisesRegex(ValueError, "source policy rejected"):
                harness.verify_audit(self.root, frozen, case)

    def test_reviewed_flag_without_visual_or_glb_binding_is_rejected(self):
        frozen, case, directory, image = self.audit_fixture()
        with patch.object(harness, "candidate_quality", return_value={"ok": True, "source_rgb": harness.bound(image)}), patch.object(harness, "audit_asset_source_policy", return_value={"ok": True}):
            visual = harness.read_json(directory / "visual_review.json")
            visual["geometry_multiview_passed"] = False
            harness.write_json(directory / "visual_review.json", visual)
            with self.assertRaisesRegex(ValueError, "visual review failed"):
                harness.verify_audit(self.root, frozen, case)
            visual["geometry_multiview_passed"] = True
            harness.write_json(directory / "visual_review.json", visual)
            (directory / "fixture.glb").write_bytes(b"replaced asset")
            with self.assertRaisesRegex(ValueError, "GLB content changed"):
                harness.verify_audit(self.root, frozen, case)

    def test_missing_real_scenes_cannot_be_accepted(self):
        with patch.object(harness, "verify_prepared", return_value={"coverage": {provider: ["storage_box"] for provider in harness.PROVIDERS}, "content_key": "test-only"}):
            report = harness.verify(self.root, self.root / "output")
        self.assertFalse(report["accepted"])
        self.assertFalse(report["automated_accepted"])
        self.assertTrue(all(row["status"] == "incomplete_or_invalid" for row in report["scenes"].values()))

    def test_prepare_requires_both_providers_and_selects_lowest_accepted_replicate(self):
        rows = {}
        for provider, replicate in (("builtin_imagegen", 2), ("builtin_imagegen", 1), ("flux1-schnell", 1)):
            identifier = f"storage_box__{provider}__r{replicate}"
            case = {"id": identifier, "category": "storage_box", "provider": provider, "replicate": replicate, "dimensions": harness.DIMENSIONS["storage_box"], "prompt": "test-only"}
            asset_path, obj_path = self.root / f"{identifier}.glb", self.root / f"{identifier}.json"
            tetrahedron_glb(asset_path)
            harness.write_json(obj_path, _object(case))
            rows[identifier] = {"case": case, "asset": harness.bound(asset_path), "generation_key": "test-only", "generation": {"job_id": identifier}, "evidence": {"asset_object": harness.bound(obj_path), "audit_certificate": harness.bound(obj_path)}}
        plan = {"test_only": True}
        frozen = {"cases": [row["case"] for row in rows.values()], "preregistration_hash": content_hash(plan)}
        frozen["content_key"] = content_hash(frozen)
        harness.write_json(self.root / "frozen_plan.json", plan)
        harness.write_json(self.root / "frozen_cases.json", frozen)
        def valid_audit(root, frozen, case):
            return deepcopy(rows[case["id"]])
        with patch.object(harness, "verify_audit", side_effect=valid_audit), patch.object(harness, "audit_asset_source_policy", return_value={"ok": True}):
            output = self.root / "output"
            prepared = harness.prepare(self.root, output)
            self.assertEqual(prepared["status"], "prepared_not_rendered")
            self.assertEqual(prepared["scenes"]["builtin_imagegen"]["object_ids"], ["storage_box__builtin_imagegen__r1"])
            resolution = harness.read_json(output / "builtin_imagegen" / "asset_resolution.json")
            self.assertEqual(resolution["results"][0]["status"], "generated")
            self.assertEqual(resolution["results"][0]["lifecycle"]["status"], "generated_for_run")
        def missing_flux(root, frozen, case):
            if case["provider"] == "flux1-schnell":
                raise ValueError("unreviewed asset")
            return valid_audit(root, frozen, case)
        with patch.object(harness, "verify_audit", side_effect=missing_flux):
            with self.assertRaisesRegex(ValueError, "both providers"):
                harness.prepare(self.root, self.root / "missing_flux")


if __name__ == "__main__":
    unittest.main()
