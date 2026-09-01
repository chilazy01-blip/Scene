from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sage.experiments.codex_trellis_scene_v2.asset_admission import (
    COUNT_EVIDENCE_SCHEMA,
    audit_library_coverage,
    build_count_contract,
    evaluate_temporary_admission,
    new_lifecycle_record,
    transition_lifecycle,
    validate_count_evidence,
)
from sage.experiments.codex_trellis_scene_v2.content_chain import (
    build_generation_contract,
    content_hash,
    file_binding,
)
from sage.experiments.codex_trellis_scene_v2.brief import (
    build_asset_generation_spec,
    render_asset_prompt,
)
from sage.experiments.codex_trellis_scene_v2.assets import AssetRegistry
from sage.experiments.codex_trellis_scene_v2.io_utils import write_json


def binding(seed: str) -> dict:
    return {"bytes": 10, "sha256": (seed * 64)[:64]}


def count_evidence(contract: dict, count: int = 5) -> dict:
    signatures = [f"book-{index}" for index in range(count)]
    return {
        "schema": COUNT_EVIDENCE_SCHEMA,
        "count_contract_hash": contract["contract_hash"],
        "review_method": "human_visual_review",
        "reviewer_id": "independent-reviewer",
        "views": {
            "front": {
                "image": binding("a"),
                "observed_count": count,
                "member_signatures": signatures,
            },
            "back": {
                "image": binding("b"),
                "observed_count": count,
                "member_signatures": list(reversed(signatures)),
            },
            "left_side": {
                "image": binding("c"),
                "observed_depth_layers": 1,
                "second_row_detected": False,
            },
            "right_side": {
                "image": binding("d"),
                "observed_depth_layers": 1,
                "second_row_detected": False,
            },
        },
    }


class AssetCountContractTest(unittest.TestCase):
    def test_generation_spec_and_prompt_preserve_explicit_count_contract(self) -> None:
        spec = build_asset_generation_spec(
            {
                "id": "books",
                "category": "book_stack",
                "dimensions": {"width": 0.4, "length": 0.15, "height": 0.35},
                "count_contract": {
                    "component_category": "book",
                    "expected_count": 5,
                    "arrangement": "single_row",
                },
            },
            ["modern"],
            "five books",
        )
        self.assertEqual(spec["count_contract"]["expected_count"], 5)
        prompt = render_asset_prompt(spec)
        self.assertIn("exactly 5 distinct books", prompt)
        self.assertIn("side views must show no second row", prompt)

    def test_exact_front_back_same_group_and_single_row_pass(self) -> None:
        contract = build_count_contract(
            component_category="book", expected_count=5
        )
        self.assertTrue(validate_count_evidence(contract, count_evidence(contract))["ok"])

    def test_ten_books_are_rejected_for_five_book_contract(self) -> None:
        contract = build_count_contract(
            component_category="book", expected_count=5
        )
        result = validate_count_evidence(contract, count_evidence(contract, 10))
        self.assertFalse(result["ok"])
        self.assertIn("exact_count:front", result["failures"])

    def test_different_front_and_back_groups_are_rejected(self) -> None:
        contract = build_count_contract(
            component_category="book", expected_count=5
        )
        evidence = count_evidence(contract)
        evidence["views"]["back"]["member_signatures"][0] = "different-book"
        result = validate_count_evidence(contract, evidence)
        self.assertIn("front_back_group_mismatch", result["failures"])

    def test_second_side_row_is_rejected(self) -> None:
        contract = build_count_contract(
            component_category="book", expected_count=5
        )
        evidence = count_evidence(contract)
        evidence["views"]["left_side"]["observed_depth_layers"] = 2
        evidence["views"]["left_side"]["second_row_detected"] = True
        result = validate_count_evidence(contract, evidence)
        self.assertIn("side_depth_layers:left_side", result["failures"])
        self.assertIn("second_row:left_side", result["failures"])


class AssetLifecycleTest(unittest.TestCase):
    def test_registry_never_reuses_non_curated_generated_asset(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "candidate.glb").write_bytes(b"candidate")
            (root / "curated.glb").write_bytes(b"curated")
            manifest = root / "manifest.json"
            write_json(
                manifest,
                {
                    "assets": [
                        {
                            "asset_id": "candidate",
                            "category": "book_stack",
                            "qa_status": "approved",
                            "lifecycle_status": "candidate_for_curation",
                            "glb_path": "candidate.glb",
                        },
                        {
                            "asset_id": "curated",
                            "category": "book_stack",
                            "qa_status": "approved",
                            "lifecycle_status": "curated",
                            "glb_path": "curated.glb",
                        },
                    ]
                },
            )

            selected = AssetRegistry(manifest).find("book_stack", [])

        self.assertEqual(selected["asset_id"], "curated")

    def test_single_scene_success_cannot_skip_to_curated(self) -> None:
        admission = {
            "lifecycle_status": "scene_specific_approved",
            "admission_hash": "a" * 64,
        }
        record = new_lifecycle_record("books", admission)
        with self.assertRaisesRegex(ValueError, "illegal asset lifecycle transition"):
            transition_lifecycle(
                record,
                "curated",
                evidence={
                    "independent_review_accepted": True,
                    "license_id": "internal",
                    "qa_hash": "b" * 64,
                },
            )

    def test_explicit_review_path_can_curate(self) -> None:
        record = new_lifecycle_record(
            "books",
            {
                "lifecycle_status": "scene_specific_approved",
                "admission_hash": "a" * 64,
            },
        )
        record = transition_lifecycle(
            record,
            "candidate_for_curation",
            evidence={"scene_independent_review_requested": True},
        )
        record = transition_lifecycle(
            record,
            "curated",
            evidence={
                "independent_review_accepted": True,
                "license_id": "project-generated-internal",
                "qa_hash": "b" * 64,
            },
        )
        self.assertEqual(record["status"], "curated")
        self.assertEqual(len(record["history"]), 3)

    def test_library_coverage_requires_three_assets_two_styles_and_metadata(self) -> None:
        entries = []
        for index in range(3):
            entries.append(
                {
                    "asset_id": f"books-{index}",
                    "category": "book_stack",
                    "lifecycle_status": "curated",
                    "qa_status": "approved",
                    "style_signature": "bold" if index < 2 else "pastel",
                    "canonical_front": {"axis": "+y"},
                    "handedness": "not_applicable",
                    "dimension_policy": {"mode": "fixed_physical"},
                    "capability": {"hash": content_hash(index)},
                    "license": {"id": "internal"},
                    "asset_sha256": content_hash({"asset": index}),
                    "qa_hash": content_hash({"qa": index}),
                    "known_failure_scenarios": [],
                }
            )
        self.assertTrue(audit_library_coverage(entries, ["book_stack"])["ok"])
        entries[2].pop("license")
        self.assertFalse(audit_library_coverage(entries, ["book_stack"])["ok"])


class TemporaryAdmissionTest(unittest.TestCase):
    def test_glb_load_alone_is_not_enough_but_complete_evidence_passes(self) -> None:
        with TemporaryDirectory() as directory:
            asset = Path(directory) / "books.glb"
            asset.write_bytes(b"valid-test-glb-binding")
            count_contract = build_count_contract(
                component_category="book", expected_count=5
            )
            generation_spec = {
                "schema": "codex_trellis_single_asset_spec_v1",
                "category": "book_stack",
                "count_contract": count_contract,
            }
            generation_contract = build_generation_contract(
                category="book_stack",
                prompt="exactly five books",
                target_dimensions_m={"width": 0.34, "length": 0.14, "height": 0.37},
                seed=7,
                model_fingerprint="trellis-model",
                rmbg_fingerprint="rmbg-model",
                pipeline_type="512",
                steps=12,
                texture_size=512,
                decimation_target=500000,
                preprocess_image=True,
                code_version="test-version",
            )
            capability = {
                "schema": "codex_trellis_asset_capability_v1",
                "asset_id": "books",
                "category": "book_stack",
                "source_asset": {**file_binding(asset), "qa_status": "approved"},
                "coordinate_frame": {
                    "units": "meters",
                    "up_axis": "z",
                    "origin": "footprint_center_base",
                    "source_mesh_up_axis": "y",
                    "source_mesh_up_sign": 1,
                    "canonical_dimensions": {
                        "width": 0.34,
                        "length": 0.14,
                        "height": 0.37,
                    },
                    "asset_axis_to_z": 2,
                    "asset_axis_to_z_sign": 1,
                    "asset_local_yaw_offset_degrees": 0,
                },
                "dimension_policy": {
                    "mode": "fixed_physical",
                    "relative_tolerance": 0.08,
                    "enforce_at_assembly": True,
                },
                "collision_proxy": {
                    "representation": "voxel_sdf",
                    "source_glb": "books.glb",
                    "voxel_pitch_m": 0.01,
                    "padding_voxels": 4,
                    "fill_interior": True,
                    "surface_dilation_voxels": 0,
                    "sign_strategy": "filled_voxel_occupancy_edt",
                    "source_requires_watertight": False,
                },
                "support_surfaces": [],
                "containment_volumes": [],
                "free_space_volumes": [],
                "included_components": {"book": 5},
            }
            common = {
                "generation_spec": generation_spec,
                "generation_contract": generation_contract,
                "candidate_2d_qa": {
                    "alpha": {"ok": True},
                    "semantic": {"ok": True},
                    "count": {
                        "ok": True,
                        "observed_count": 5,
                        "image": binding("e"),
                    },
                },
                "trellis_generation": {"ok": True, "job_id": "job-7"},
                "multiview_qa": {
                    "evaluated": True,
                    "rendered_view_count": 4,
                    "missing_views": [],
                    "hard_geometry_gate_passed": True,
                    "automated_pixel_multiview_pass": True,
                },
                "dimension_qa": {"accepted": True, "measured_from_glb": True},
                "orientation_qa": {
                    "accepted": True,
                    "canonical_front": {"axis": "+y", "confidence": 0.95},
                },
                "topology_qa": {
                    "trimesh_load_ok": True,
                    "finite_bounds": True,
                    "face_count": 100,
                    "cleanup_accepted": True,
                },
                "capability": capability,
                "count_evidence": count_evidence(count_contract),
            }
            accepted = evaluate_temporary_admission(asset, **common)
            self.assertTrue(accepted["accepted"])
            self.assertEqual(accepted["lifecycle_status"], "scene_specific_approved")
            incomplete = dict(common)
            incomplete["candidate_2d_qa"] = {
                "alpha": {"ok": True},
                "semantic": {"ok": False},
                "count": {
                    "ok": True,
                    "observed_count": 5,
                    "image": binding("e"),
                },
            }
            rejected = evaluate_temporary_admission(asset, **incomplete)
            self.assertFalse(rejected["accepted"])
            self.assertIn("candidate_2d_semantic", rejected["failures"])
            self.assertEqual(rejected["lifecycle_status"], "generated_for_run")


if __name__ == "__main__":
    unittest.main()
