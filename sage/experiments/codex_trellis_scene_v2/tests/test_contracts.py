from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.content_chain import make_artifact_certificate
from sage.experiments.codex_trellis_scene_v2.contracts import (
    COORDINATES,
    ContractError,
    canonical_document_hash,
    migrate_document,
    migrate_layout_plan,
    stamp_document,
    validate_document_family,
    validate_layout_plan,
)
from sage.experiments.codex_trellis_scene_v2.runtime_preflight import validate_runtime_lock_document
from sage.experiments.codex_trellis_scene_v2.stage_dag import STAGES


def valid_plan() -> dict:
    return stamp_document(
        {
            "schema": "codex_trellis_layout_plan_v2",
            "coordinate_contract": COORDINATES.as_dict(),
            "instance_groups": [],
            "objects": [
                {
                    "id": "chair",
                    "yaw": 90.0,
                    "asset_source_up": "+y",
                    "asset_axis_to_z": 1,
                    "asset_canonical_front": {"axis": "+y"},
                }
            ],
        }
    )


class ContractTests(unittest.TestCase):
    def test_valid_coordinate_and_layout_contract(self) -> None:
        validate_layout_plan(valid_plan())

    def test_wrong_units_world_axis_asset_axis_legacy_and_missing_group_rejected(self) -> None:
        cases = []
        wrong_units = valid_plan()
        wrong_units["coordinate_contract"] = {**COORDINATES.as_dict(), "units": "cm"}
        cases.append(wrong_units)
        wrong_world = valid_plan()
        wrong_world["coordinate_contract"] = {**COORDINATES.as_dict(), "world_up": "+y"}
        cases.append(wrong_world)
        wrong_asset_axis = valid_plan()
        wrong_asset_axis["objects"][0]["asset_axis_to_z"] = 2
        cases.append(wrong_asset_axis)
        old_field = valid_plan()
        old_field["objects"][0]["rotation_y"] = 1.0
        cases.append(old_field)
        orphan = valid_plan()
        orphan["objects"][0]["instance_group_id"] = "missing"
        cases.append(orphan)
        missing_groups = valid_plan()
        del missing_groups["instance_groups"]
        cases.append(missing_groups)
        unknown_coordinate = valid_plan()
        unknown_coordinate["coordinate_contract"]["scale"] = 100
        cases.append(unknown_coordinate)
        for case in cases:
            stamp_document(case)
            with self.subTest(case=case):
                with self.assertRaises(ContractError):
                    validate_layout_plan(case)

    def test_only_known_old_schema_migrates(self) -> None:
        old = {
            "schema": "codex_trellis_layout_plan_v1",
            "objects": [{"id": "x", "yaw_degrees": 0.0}],
        }
        migrated = migrate_layout_plan(old)
        self.assertEqual(migrated["schema"], "codex_trellis_layout_plan_v2")
        self.assertEqual(migrated["objects"][0]["yaw"], 0.0)
        with self.assertRaises(ContractError):
            migrate_layout_plan({"schema": "mystery", "objects": []})
        with self.assertRaises(ContractError):
            migrate_document("SceneBrief", {"schema": "codex_trellis_scene_brief_v1"})

    def test_canonical_document_hash_is_order_stable_and_tamper_evident(self) -> None:
        first = {"schema": "x", "nested": {"b": 2, "a": 1}}
        second = {"nested": {"a": 1, "b": 2}, "schema": "x"}
        self.assertEqual(canonical_document_hash(first), canonical_document_hash(second))
        stamp_document(first)
        first["nested"]["a"] = 3
        self.assertNotEqual(first["content_hash"], canonical_document_hash(first))

    def test_all_seven_document_families_have_executable_validation(self) -> None:
        brief = stamp_document(
            {
                "schema": "codex_trellis_scene_brief_v2",
                "coordinate_contract": COORDINATES.as_dict(),
                "original_prompt": "one chair",
                "room_type": "study",
                "room": {"width": 4.0, "length": 3.0, "height": 2.7},
                "objects": [{"id": "chair", "category": "chair", "dimensions": {"width": 0.6, "length": 0.6, "height": 0.9}}],
                "instance_groups": [],
            }
        )
        graph = stamp_document(
            {
                "schema": "codex_trellis_typed_scene_graph_v1",
                "coordinate_contract": COORDINATES.as_dict(),
                "root_id": "room",
                "nodes": [{"id": "room", "parent_id": None}, {"id": "chair", "parent_id": "room"}],
                "relations": [{"source": "chair", "target": "room", "type": "contained_in"}],
                "validation": {"ok": True},
            }
        )
        relation = stamp_document({"schema": "scene-v2-production-relation-geometry-stage/v1", "ok": True, "declared_relation_count": 0})
        manifest = stamp_document(
            {
                "schema": "scene-v2-stage-dag/v1",
                "stage_order": list(STAGES),
                "stages": {stage: {"dependencies": [], "attempts": []} for stage in STAGES},
            }
        )
        final_audit = stamp_document({"schema": "scene-v2-final-hash-audit/v1", "ok": True, "missing": [], "artifacts": {}})
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "asset.glb"
            artifact.write_bytes(b"glb")
            asset_certificate = make_artifact_certificate(artifact, upstream={"seed": 1}, rules={"qa": "v1"})
            documents = {
                "SceneBrief": brief,
                "TypedSceneGraph": graph,
                "AssetQACertificate": asset_certificate,
                "LayoutPlan": valid_plan(),
                "RelationCertificate": relation,
                "RunManifest": manifest,
                "FinalDeliveryAudit": final_audit,
            }
            for family, document in documents.items():
                with self.subTest(family=family):
                    validate_document_family(family, document)

    def test_runtime_lock_rejects_unknown_or_missing_environment(self) -> None:
        path = Path(__file__).resolve().parents[1] / "runtime_lock.json"
        lock = json.loads(path.read_text(encoding="utf-8"))
        validate_runtime_lock_document(lock)
        missing = deepcopy(lock)
        del missing["environments"]["research"]
        with self.assertRaises(ValueError):
            validate_runtime_lock_document(missing)
        unknown = deepcopy(lock)
        unknown["silent_fallback"] = True
        with self.assertRaises(ValueError):
            validate_runtime_lock_document(unknown)


if __name__ == "__main__":
    unittest.main()
