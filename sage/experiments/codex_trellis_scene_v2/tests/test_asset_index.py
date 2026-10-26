from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.asset_index import AssetIndex, AssetIndexBuilder, text_vector
from sage.experiments.codex_trellis_scene_v2.assets import AssetRegistry


class AssetIndexTest(unittest.TestCase):
    def test_hard_filters_run_before_vector_recall(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "assets.sqlite"
            vector = text_vector(["chair", "modern"]).tolist()
            records = [
                {"asset_id": "good", "category": "chair", "styles": ["modern"], "qa_status": "approved", "lifecycle_status": "curated", "license": "cc0", "capabilities": ["sittable"], "retrieval_vector": vector},
                {"asset_id": "bad_qa", "category": "chair", "qa_status": "rejected", "lifecycle_status": "curated", "license": "cc0", "capabilities": ["sittable"], "retrieval_vector": vector},
                {"asset_id": "bad_lifecycle", "category": "chair", "qa_status": "approved", "lifecycle_status": "candidate_for_curation", "license": "cc0", "capabilities": ["sittable"], "retrieval_vector": vector},
                {"asset_id": "bad_license", "category": "chair", "qa_status": "approved", "lifecycle_status": "curated", "license": "forbidden", "capabilities": ["sittable"], "retrieval_vector": vector},
                {"asset_id": "bad_capability", "category": "chair", "qa_status": "approved", "lifecycle_status": "curated", "license": "cc0", "capabilities": [], "retrieval_vector": vector},
            ]
            with AssetIndexBuilder(path) as builder:
                builder.upsert(records)
                builder.finalize()
            index = AssetIndex(path)
            result = index.query(category="chair", vector=vector, required_capabilities=["sittable"])
            self.assertEqual([item["asset_id"] for item in result["results"]], ["good"])
            self.assertTrue(result["hard_filters_applied_before_vector_recall"])
            index.close()

    def test_update_delete_change_version_and_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "assets.sqlite"
            record = {"asset_id": "one", "category": "desk", "styles": ["warm"], "qa_status": "approved", "lifecycle_status": "curated", "license": "cc0"}
            with AssetIndexBuilder(path) as builder:
                builder.upsert([record])
                first_meta = builder.finalize()
            first = AssetIndex(path)
            first_result = first.query(category="desk", styles=["warm"])
            first.close()
            record["styles"] = ["cool"]
            with AssetIndexBuilder(path) as builder:
                builder.upsert([record])
                second_meta = builder.finalize()
                self.assertEqual(builder.delete(["one"]), 1)
                third_meta = builder.finalize()
            self.assertNotEqual(first_meta["index_version"], second_meta["index_version"])
            self.assertNotEqual(second_meta["index_version"], third_meta["index_version"])
            second = AssetIndex(path)
            second_result = second.query(category="desk", styles=["warm"])
            self.assertNotEqual(first_result["cache_key"], second_result["cache_key"])
            self.assertEqual(second_result["results"], [])
            second.close()

    def test_manifest_binding_rejects_stale_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "manifest.json"
            manifest.write_text('{"assets":[]}', encoding="utf-8")
            index_path = manifest.with_suffix(".asset_index.sqlite")
            with AssetIndexBuilder(index_path, source_manifest=manifest) as builder:
                builder.finalize()
            manifest.write_text('{"assets":[],"changed":true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                AssetIndex(index_path, expected_manifest=manifest)

    def test_asset_registry_uses_sidecar_and_preserves_deterministic_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("one", "two"):
                (root / f"{name}.glb").write_bytes(b"glTF")
            assets = [
                {"asset_id": "one", "category": "nightstand", "styles": ["modern"], "qa_status": "approved", "lifecycle_status": "curated", "license": "cc0", "glb_path": "one.glb"},
                {"asset_id": "two", "category": "nightstand", "styles": ["modern"], "qa_status": "approved", "lifecycle_status": "curated", "license": "cc0", "glb_path": "two.glb"},
            ]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"assets": assets}), encoding="utf-8")
            with AssetIndexBuilder(manifest.with_suffix(".asset_index.sqlite"), source_manifest=manifest) as builder:
                builder.upsert(assets)
                builder.finalize()
            registry = AssetRegistry(manifest)
            registry.prefetch([{"category": "nightstand", "styles": ["modern"]}])
            first = registry.find("nightstand", ["modern"], variant_index=0)
            second = registry.find("nightstand", ["modern"], variant_index=1)
            self.assertEqual([first["asset_id"], second["asset_id"]], ["one", "two"])
            self.assertIn("_asset_index_retrieval", first)
            self.assertTrue(registry.index_queries[-1]["cache_hit"])


if __name__ == "__main__":
    unittest.main()
