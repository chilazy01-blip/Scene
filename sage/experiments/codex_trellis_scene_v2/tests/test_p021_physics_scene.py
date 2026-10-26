"""P021 admission/geometry failures; tetrahedra below are mathematical tests only."""

from copy import deepcopy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .. import p021_physics_scene as scene
from .test_p019_scene_validation import tetrahedron_glb


INVENTORY = (Path(__file__).resolve().parents[5] / "scene_runs/codex_trellis_v2/"
             "p019_p021_longrun_20260905_v1/p021/ASSET_INVENTORY.json")


def spec_fixture():
    return {"schema": scene.SPEC_SCHEMA, "run_id": "unit-test-only", "method": "A_support_priority",
            "floor_mu": 0.3, "parameter_origin": "designed_test_coefficient", "measured_asset_friction": None,
            "development": True, "room": {"width": 6, "length": 5, "height": 2.8},
            "objects": [{"id": "bookcase__builtin_imagegen__r2", "inventory_id": "bookcase_r2",
                         "x": 2.2, "y": 1.4, "z": 0, "yaw": 0},
                        {"id": "sofa__builtin_imagegen__r1", "inventory_id": "sofa_builtin_r1_engineering",
                         "x": 2.2, "y": 3.4, "z": 0, "yaw": 0}],
            "simulation": {"dt": 0.002, "settle_s": 1, "action_s": 2,
                           "sample_interval_s": 0.1, "initial_velocity_m_s": [1.5, 0, 0]}}


def inventory_fixture():
    return {"schema": "p021-readonly-asset-inventory/v1",
            "selected_assets": [{"inventory_id": key, "object_id": value[0],
                                 "category": value[1], "curated": False} for key, value in scene.ADMITTED.items()]}


def mutate_glb_document(path, mutate):
    document, binary = scene.core.glb_document(path)
    mutate(document)
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(body) + len(binary)) +
                     struct.pack("<II", len(body), 0x4E4F534A) + body +
                     struct.pack("<II", len(binary), 0x004E4942) + binary)


class P021SpecTests(unittest.TestCase):
    def test_holdout_selects_exact_r1_without_aliasing_source_identity(self):
        spec = spec_fixture()
        spec["objects"][0].update(id="bookcase__builtin_imagegen__r1", inventory_id="bookcase_r1", x=2.8, y=1.8)
        self.assertEqual([row["inventory_id"] for row in scene.validate_spec(spec, inventory_fixture())],
                         ["bookcase_r1", "sofa_builtin_r1_engineering"])

    def test_missing_extra_duplicate_and_relabelled_objects_are_rejected(self):
        base = spec_fixture()
        variants = []
        missing = deepcopy(base); missing["objects"].pop(); variants.append(missing)
        extra = deepcopy(base); extra["objects"].append(deepcopy(base["objects"][0])); variants.append(extra)
        duplicate = deepcopy(base); duplicate["objects"][1] = deepcopy(base["objects"][0]); variants.append(duplicate)
        relabelled = deepcopy(base); relabelled["objects"][0]["id"] = "bookcase"; variants.append(relabelled)
        conditional = deepcopy(base); conditional["objects"][0]["inventory_id"] = "p020_closed_box"; variants.append(conditional)
        for spec in variants:
            with self.subTest(objects=spec["objects"]), self.assertRaises(ValueError):
                scene.validate_spec(spec, inventory_fixture())

    def test_nonfinite_physics_and_unreviewed_geometry_overrides_are_rejected(self):
        for key, value in (("yaw", 180), ("z", 0.3), ("x", float("nan")),
                           ("asset_axis_to_z", 1), ("dimensions", {"width": 5})):
            spec = spec_fixture(); spec["objects"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                scene.validate_spec(spec, inventory_fixture())
        for mu in (0, -0.3, float("nan"), float("inf"), True):
            spec = spec_fixture(); spec["floor_mu"] = mu
            with self.subTest(mu=mu), self.assertRaises(ValueError):
                scene.validate_spec(spec, inventory_fixture())
        spec = spec_fixture(); spec["measured_asset_friction"] = 0.3
        with self.assertRaisesRegex(ValueError, "no measured"):
            scene.validate_spec(spec, inventory_fixture())

    def test_reused_flag_cannot_promote_the_original_generated_asset(self):
        inventory = inventory_fixture()
        inventory["selected_assets"][1]["curated"] = True
        with self.assertRaisesRegex(ValueError, "promoted"):
            scene.validate_spec(spec_fixture(), inventory)


class P021FinalGeometryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.glb = self.root / "source.glb", self.root / "scene.glb"
        tetrahedron_glb(self.source)
        self.matrix = np.eye(4)
        self.matrix[:3, 3] = [1.5, 0, -3.5]
        tetrahedron_glb(self.glb, root=self.matrix, object_id="fixture")
        self.plan = {"objects": [{"id": "fixture", "x": 2, "y": 3, "z": 0, "yaw": 0,
                                   "dimensions": {"width": 1, "length": 1, "height": 1}}],
                     "room": {"width": 5, "length": 5, "height": 3}, "relations": []}
        self.rows = [{"case": {"id": "fixture"}, "asset": scene.bound(self.source),
                      "staged_asset": scene.bound(self.source), "generation_key": "test-only"}]

    def test_source_correspondence_detects_changed_mesh_inside_identical_node_ids(self):
        self.assertTrue(scene.inspect_final_scene(self.glb, self.plan, self.rows)["accepted"])
        tetrahedron_glb(self.glb, root=self.matrix, object_id="fixture", offset=0.03)
        result = scene.inspect_final_scene(self.glb, self.plan, self.rows)
        self.assertFalse(result["accepted"])
        self.assertIn("fixture:geometry_matches_reviewed_glb", result["failures"])

    def test_half_turn_is_rejected_even_when_bounding_box_and_correspondence_pass(self):
        matrix = np.diag([-1., 1., -1., 1.])
        matrix[:3, 3] = [2.5, 0, -2.5]
        tetrahedron_glb(self.glb, root=matrix, object_id="fixture")
        self.assertTrue(scene.core.inspect_scene(self.glb, self.plan, self.rows)["accepted"])
        result = scene.inspect_final_scene(self.glb, self.plan, self.rows)
        self.assertFalse(result["accepted"])
        self.assertIn("fixture:original_positive_scale_axes_and_yaw_preserved", result["failures"])

    def test_missing_and_extra_exported_id_are_rejected(self):
        for value in (None, "unexpected_furniture"):
            tetrahedron_glb(self.glb, root=self.matrix, object_id="fixture")
            def change(document):
                for node in document["nodes"]:
                    node["extras"] = {} if value is None else {"scene_object_id": value}
            mutate_glb_document(self.glb, change)
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "furniture object IDs differ"):
                scene.inspect_final_scene(self.glb, self.plan, self.rows)

    def test_untagged_extra_mesh_is_rejected_without_relying_on_scene_object_id(self):
        def change(document):
            document["nodes"].append({"name": "unbound_extra_furniture", "mesh": 0})
            document["scenes"][0]["nodes"].append(len(document["nodes"]) - 1)
        mutate_glb_document(self.glb, change)
        with self.assertRaisesRegex(ValueError, "unexpected untagged"):
            scene.inspect_final_scene(self.glb, self.plan, self.rows)

    def test_staged_source_byte_mutation_is_rejected(self):
        self.source.write_bytes(self.source.read_bytes() + b"changed source")
        with self.assertRaisesRegex(ValueError, "file content changed"):
            scene.inspect_final_scene(self.glb, self.plan, self.rows)


@unittest.skipUnless(INVENTORY.is_file(), "optional integration requires preserved real P019 evidence")
class P021OriginalSourceIntegrationTests(unittest.TestCase):
    """Read-only actual provenance integration; only temporary copies are mutated."""

    @classmethod
    def setUpClass(cls):
        cls.inventory = scene.read_json(INVENTORY)
        cls.entries = {row["inventory_id"]: row for row in cls.inventory["selected_assets"]}

    def test_both_bookcases_and_separately_scoped_sofa_revalidate_actual_original_evidence(self):
        for identifier in scene.ADMITTED:
            with self.subTest(identifier=identifier):
                entry = self.entries[identifier]
                row = scene.revalidate_asset(entry)
                self.assertEqual(row["asset"], entry["glb"])
                self.assertEqual(row["generation"], scene.read_json(Path(entry["entrypoint_files"]["generation"]["path"])))
                self.assertFalse(row["reuse"]["new_generation"])
                self.assertFalse(row["reuse"]["auto_curated"])
                self.assertIsNone(row["scoped_admission"]["independent_human_validation"])
                if entry["category"] == "sofa":
                    self.assertFalse(row["original_full_specification_passed"])
                    self.assertTrue(row["original_quality_findings"])
                    self.assertIn("engineering_asset_review", row["evidence"])
                else:
                    self.assertIn("visual_review", row["evidence"])

    def test_mutated_original_review_copy_is_rejected_before_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = deepcopy(self.entries["bookcase_r2"])
            original = entry["entrypoint_files"]["visual_review"]
            copy = Path(directory) / "visual_review.json"
            content = scene.read_json(Path(original["path"]))
            content["geometry_multiview_passed"] = False
            scene.write_json(copy, content)
            original["path"] = str(copy)
            with self.assertRaisesRegex(ValueError, "file content changed"):
                scene.revalidate_asset(entry)

    def test_inventoried_hash_and_orientation_mutations_are_rejected(self):
        entry = deepcopy(self.entries["bookcase_r2"])
        entry["glb"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "file content changed"):
            scene.revalidate_asset(entry)
        entry = deepcopy(self.entries["bookcase_r2"])
        entry["orientation"]["asset_axis_to_z_sign"] = -1
        with self.assertRaisesRegex(ValueError, "orientation changed"):
            scene.revalidate_asset(entry)

    def test_real_layout_overlap_fails_before_staging_or_blender(self):
        spec = spec_fixture()
        spec["objects"][1].update(x=2.2, y=1.4)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path, spec_path = root / "inventory.json", root / "spec.json"
            scene.write_json(inventory_path, self.inventory)
            scene.write_json(spec_path, spec)
            with patch.object(scene.runtime, "assemble_with_blender") as assemble:
                with self.assertRaisesRegex(ValueError, "layout rejected"):
                    scene.prepare_scene(spec_path, root / "output", inventory_path, Path(__file__))
                assemble.assert_not_called()
            result = scene.read_json(root / "output/prepare_result.json")
            self.assertFalse(result["ok"])
            self.assertEqual(result["failed_stage"], "new_request_layout_and_source_gates")
            self.assertFalse((root / "output/assets").exists())
            self.assertFalse((root / "output/scene.glb").exists())

    def test_actual_canonical_runtime_error_preserves_failure_and_unmodified_staging(self):
        # A real /bin/false subprocess exercises runtime failure handling without
        # starting Blender or manufacturing an assembled scene.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory_path, spec_path = root / "inventory.json", root / "spec.json"
            scene.write_json(inventory_path, self.inventory)
            scene.write_json(spec_path, spec_fixture())
            with self.assertRaisesRegex(RuntimeError, "Blender assembly failed"):
                scene.prepare_scene(spec_path, root / "output", inventory_path, Path("/bin/false"))
            result = scene.read_json(root / "output/prepare_result.json")
            self.assertFalse(result["ok"])
            self.assertEqual(result["failed_stage"], "canonical_blender_assembly")
            self.assertFalse((root / "output/scene.glb").exists())
            references = scene.read_json(root / "output/asset_references.json")
            for row in references["assets"]:
                self.assertEqual(scene.file_binding(Path(row["asset"]["path"])),
                                 scene.file_binding(Path(row["staged_asset"]["path"])))
            with self.assertRaisesRegex(ValueError, "immutable"):
                scene.prepare_scene(spec_path, root / "output", inventory_path, Path("/bin/false"))


if __name__ == "__main__":
    unittest.main()
