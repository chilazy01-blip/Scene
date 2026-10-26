from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ..detail_repair_agent import (
    build_repair_plan,
    diagnose_detail_failures,
    rank_repair_references,
    verify_repair,
)
from ..detail_repair_runner import (
    _attempt_review_priority,
    summarize_detail_repair_results,
)
from ..detail_face_localizer import (
    apply_generic_connected_platform_gate,
    generic_connected_platform_evidence,
    localize_lower_platform_faces,
    tessellation_aware_platform_repair_policy,
)


def _report(
    *,
    hard: bool,
    platform: bool = False,
    semantic: float = 0.55,
    semantic_verified: bool = True,
    style: float = 0.65,
    style_verified: bool = True,
    border: float = 0.0,
) -> dict:
    return {
        "evaluated": True,
        "rendered_view_count": 4,
        "missing_views": [],
        "hard_geometry_gate_passed": hard,
        "automated_score": 0.65,
        "views": {
            axis: {"border_foreground_ratio": border, "ok": border <= 0.02}
            for axis in ("+x", "-x", "+y", "-y")
        },
        "structure_gate": {
            "basic_foreground_passed": border <= 0.02,
            "general_fragment_passed": True,
            "compact_silhouette_passed": True,
            "internal_hole_passed": True,
            "lower_overhang_passed": True,
            "lower_platform_passed": not platform,
        },
        "opposite_view_consistency": {"passes": True, "minimum_pair_score": 0.9},
        "scale_anisotropy_gate": {"passes": True, "actual": 1.2},
        "semantic_category_verified": semantic_verified,
        "semantic_style_verified": style_verified,
        "semantic_style_multiview": {
            "evaluated": True,
            "mean_semantic_score": semantic,
            "minimum_semantic_score": semantic - 0.05,
            "mean_style_alignment_score": style,
            "minimum_style_alignment_score": style - 0.05,
        },
    }


class DetailRepairAgentTest(unittest.TestCase):
    def test_generic_connected_platform_requires_3d_and_multiview_evidence(self) -> None:
        report = _report(hard=True)
        report["structure_gate"]["lower_to_upper_footprint_area_ratio"] = 12.0
        for axis in ("+x", "-x"):
            report["views"][axis].update(
                lower_full_width_row_fraction=0.72,
                lower_overhang_ratio=4.1,
            )
        evidence = generic_connected_platform_evidence(report)
        self.assertTrue(evidence["triggered"], evidence)
        updated = apply_generic_connected_platform_gate(report)
        self.assertFalse(updated["hard_geometry_gate_passed"])
        self.assertFalse(updated["structure_gate"]["lower_platform_passed"])

        report["structure_gate"]["lower_to_upper_footprint_area_ratio"] = 1.4
        evidence = generic_connected_platform_evidence(report)
        self.assertFalse(evidence["triggered"], evidence)

    def test_generic_connected_platform_does_not_trigger_from_one_view(self) -> None:
        report = _report(hard=True)
        report["structure_gate"]["lower_to_upper_footprint_area_ratio"] = 20.0
        report["views"]["+x"].update(
            lower_full_width_row_fraction=0.90,
            lower_overhang_ratio=8.0,
        )
        evidence = generic_connected_platform_evidence(report)
        self.assertFalse(evidence["triggered"], evidence)
        self.assertEqual(evidence["supporting_views"], ["+x"])

    def test_equal_width_failed_sofa_platform_is_rejected_without_overhang(self) -> None:
        report = _report(hard=True)
        report["structure_gate"]["lower_to_upper_footprint_area_ratio"] = 5.000076
        for axis in ("+x", "-x", "+y", "-y"):
            report["views"][axis].update(
                lower_full_width_row_fraction=1.0,
                lower_overhang_ratio=1.0,
            )

        evidence = generic_connected_platform_evidence(report)
        updated = apply_generic_connected_platform_gate(report)

        self.assertTrue(evidence["triggered"], evidence)
        self.assertTrue(evidence["layered_full_width_trigger"])
        self.assertEqual(evidence["overhang_supporting_views"], [])
        self.assertFalse(updated["hard_geometry_gate_passed"])
        self.assertFalse(updated["automated_pixel_multiview_pass"])
        self.assertEqual(
            updated["acceptance"], "rejected_connected_platform_geometry"
        )

    def test_full_width_closed_box_without_layered_footprint_anomaly_passes(self) -> None:
        report = _report(hard=True)
        report["structure_gate"]["lower_to_upper_footprint_area_ratio"] = 1.05
        for axis in ("+x", "-x", "+y", "-y"):
            report["views"][axis].update(
                lower_full_width_row_fraction=1.0,
                lower_overhang_ratio=1.0,
            )

        evidence = generic_connected_platform_evidence(report)

        self.assertFalse(evidence["triggered"], evidence)

    def test_tessellation_aware_cap_requires_exceptionally_strong_evidence(self) -> None:
        report = _report(hard=True)
        report["generic_connected_platform_evidence"] = {
            "triggered": True,
            "lower_to_upper_footprint_area_ratio": 20.0,
            "supporting_views": ["+x", "-x", "+y", "-y"],
        }
        policy = tessellation_aware_platform_repair_policy(report)
        self.assertTrue(policy["strong_platform_evidence"], policy)
        self.assertEqual(policy["maximum_removed_face_fraction"], 0.85)

        report["generic_connected_platform_evidence"]["supporting_views"] = [
            "+x",
            "-x",
        ]
        policy = tessellation_aware_platform_repair_policy(report)
        self.assertFalse(policy["strong_platform_evidence"], policy)
        self.assertEqual(policy["maximum_removed_face_fraction"], 0.50)

    def test_clipping_is_reacquired_before_regeneration(self) -> None:
        diagnosis = diagnose_detail_failures(_report(hard=False, border=0.04))
        self.assertEqual(diagnosis["findings"][0]["issue_type"], "evidence_capture_clipping")
        plan = build_repair_plan("case", diagnosis, [], max_generation_attempts=2)
        self.assertEqual(plan["actions"][0]["action"], "rerender_same_asset_with_safe_framing")
        self.assertFalse(plan["actions"][0]["mutates_asset"])

    def test_platform_failure_prioritizes_form_and_excludes_used_reference(self) -> None:
        diagnosis = diagnose_detail_failures(_report(hard=False, platform=True))
        plan = build_repair_plan("case", diagnosis, [], max_generation_attempts=2)
        self.assertEqual(plan["actions"][0]["action"], "localize_and_repair_defect_faces")
        self.assertFalse(plan["actions"][0]["costs_generation_budget"])
        self.assertEqual(plan["actions"][1]["action"], "trim_forbidden_lower_platform")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            used = root / "used.png"
            unused = root / "unused.png"
            used.touch()
            unused.touch()
            batch = {
                "reference_attempts": [
                    {"attempt": 0, "prepared_image_path": str(used)},
                    {"attempt": 1, "prepared_image_path": str(unused)},
                ],
                "scene_dna_candidate_selection": {
                    "ranking": [
                        {
                            "attempt": 0,
                            "eligible": True,
                            "score": {"score": 0.9, "form": {"score": 0.9}, "semantic": {"score": 0.9}},
                        },
                        {
                            "attempt": 1,
                            "eligible": True,
                            "score": {"score": 0.7, "form": {"score": 1.0}, "semantic": {"score": 0.6}},
                        },
                    ]
                },
            }
            ranked = rank_repair_references(batch, diagnosis, excluded_paths=[used])
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["attempt"], 1)
        self.assertEqual(ranked[0]["ranking_rationale"], "form_failure_weighting")

    def test_verified_hard_fix_commits(self) -> None:
        before = _report(hard=False, platform=True)
        after = _report(hard=True, platform=False, semantic=0.56, style=0.63)
        verification = verify_repair(before, after)
        self.assertTrue(verification["accepted"], verification)
        self.assertEqual(verification["decision"], "commit_repair")

    def test_localized_material_certificate_separates_style_from_shape(self) -> None:
        before = _report(hard=False, platform=True, semantic=0.55, style=0.70)
        after = _report(hard=True, platform=False, semantic=0.54, style=0.40)
        certificate = {
            "schema": "scene_detail_localized_mesh_repair_v1",
            "evidence_grounded": True,
            "multi_view_confirmed": True,
            "removed_face_fraction": 0.40,
            "maximum_removed_face_fraction": 0.50,
            "material_preservation": {
                "verified": True,
                "surviving_face_material_assignments_preserved": True,
                "texture_and_node_parameters_modified": False,
            },
            "scope_certificate": {
                "only_seed_connected_faces_below_height_limit_removed": True,
                "preexisting_open_boundaries_filled": False,
                "whole_asset_regeneration_used": False,
            },
        }
        verification = verify_repair(
            before,
            after,
            edit_certificate=certificate,
        )
        self.assertTrue(verification["accepted"], verification)
        self.assertTrue(verification["zero_shot_style_score_regressed"])
        self.assertTrue(verification["localized_material_style_evidence_accepted"])

    def test_localized_certificate_cannot_bypass_semantic_or_scope_gate(self) -> None:
        before = _report(hard=False, platform=True, semantic=0.62, style=0.70)
        after = _report(hard=True, platform=False, semantic=0.40, style=0.40)
        certificate = {
            "schema": "scene_detail_localized_mesh_repair_v1",
            "evidence_grounded": True,
            "multi_view_confirmed": True,
            "removed_face_fraction": 0.40,
            "maximum_removed_face_fraction": 0.50,
            "material_preservation": {
                "verified": True,
                "surviving_face_material_assignments_preserved": True,
                "texture_and_node_parameters_modified": False,
            },
            "scope_certificate": {
                "only_seed_connected_faces_below_height_limit_removed": True,
                "preexisting_open_boundaries_filled": False,
                "whole_asset_regeneration_used": False,
            },
        }
        semantic_failure = verify_repair(
            before,
            after,
            edit_certificate=certificate,
        )
        self.assertFalse(semantic_failure["accepted"], semantic_failure)
        self.assertFalse(semantic_failure["regression_gates"]["semantic"])

        after = _report(hard=True, platform=False, semantic=0.61, style=0.40)
        certificate["removed_face_fraction"] = 0.51
        scope_failure = verify_repair(
            before,
            after,
            edit_certificate=certificate,
        )
        self.assertFalse(scope_failure["accepted"], scope_failure)
        self.assertFalse(scope_failure["regression_gates"]["style"])

    def test_multiview_lower_mask_localizes_low_polygon_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            object_dir = root / "asset"
            object_dir.mkdir()
            table_path = object_dir / "geometry_face_table.npz"
            np.savez_compressed(
                table_path,
                object_index=np.asarray([0, 0, 0], dtype=np.int32),
                polygon_index=np.asarray([10, 11, 12], dtype=np.int32),
                centroid_xyz=np.asarray(
                    [[-0.1, -0.3, 0.1], [0.1, -0.3, 0.2], [0.0, 0.2, 0.8]],
                    dtype=np.float32,
                ),
                centroid_z=np.asarray([0.1, 0.2, 0.8], dtype=np.float32),
                maximum_z=np.asarray([0.2, 0.25, 0.9], dtype=np.float32),
            )
            views = {}
            evidence_views = {}
            for axis in ("+x", "-x", "+y", "-y"):
                stem = axis.replace("+", "plus_").replace("-", "minus_")
                image_path = object_dir / f"{stem}.png"
                rgba = np.zeros((16, 16, 4), dtype=np.uint8)
                rgba[2:14, 3:13, :3] = 180
                rgba[2:14, 3:13, 3] = 255
                Image.fromarray(rgba, mode="RGBA").save(image_path)
                face_map = np.full((8, 8), -1, dtype=np.int32)
                face_map[1:5, 2:6] = 2
                face_map[5:7, 2:4] = 0
                evidence_path = object_dir / f"{stem}_geometry.npz"
                np.savez_compressed(
                    evidence_path,
                    face_index=face_map,
                    depth=np.ones((8, 8), dtype=np.float32),
                    normal=np.zeros((8, 8, 3), dtype=np.float32),
                )
                views[axis] = str(image_path)
                evidence_views[axis] = {
                    "path": str(evidence_path),
                    "orthographic_scale": 1.0,
                    "camera_matrix_world": [
                        [1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0],
                        [0.0, 0.0, 0.0, 1.0],
                    ],
                }
            manifest = {
                "views": {"case": views},
                "normalization": {
                    "case": {
                        "root_matrix_world": [
                            [1.0, 0.0, 0.0, 0.0],
                            [0.0, 1.0, 0.0, 0.0],
                            [0.0, 0.0, 1.0, 0.0],
                            [0.0, 0.0, 0.0, 1.0],
                        ]
                    }
                },
                "geometry_evidence": {
                    "case": {
                        "face_table_path": str(table_path),
                        "object_names": ["Mesh"],
                        "normalized_z_min": 0.0,
                        "normalized_z_max": 1.0,
                        "views": evidence_views,
                    }
                },
            }
            result = localize_lower_platform_faces(
                manifest,
                object_id="case",
                output_dir=root / "localized",
            )
            self.assertTrue(result["accepted_for_automatic_repair"], result)
            self.assertEqual(set(result["selected_seed_polygons"]["Mesh"]), {10, 11})
            self.assertEqual(result["visible_seed_face_count"], 1)
            self.assertEqual(result["projected_seed_face_count"], 2)
            self.assertEqual(set(result["supporting_views"]), {"+x", "-x", "+y", "-y"})

    def test_new_hard_failure_or_semantic_regression_rolls_back(self) -> None:
        before = _report(hard=False, platform=True, semantic=0.62)
        after = _report(hard=False, platform=False, semantic=0.40)
        after["structure_gate"]["general_fragment_passed"] = False
        verification = verify_repair(before, after)
        self.assertFalse(verification["accepted"])
        self.assertEqual(verification["decision"], "rollback_repair")
        self.assertIn("structure:fragmentation", verification["introduced_hard_failures"])

    def test_summary_counts_resolved_but_rejected_repairs(self) -> None:
        verification = verify_repair(
            _report(hard=False, platform=True),
            _report(hard=True, platform=False, semantic=0.50, style=0.40),
        )
        rows = [
            {
                "status": "unresolved_rolled_back",
                "rollback_enforced": True,
                "local_mesh_repair_attempt_count": 1,
                "generation_attempt_count": 0,
                "local_mesh_repair_attempts": [{"verification": verification}],
                "attempts": [],
            }
        ]
        summary = summarize_detail_repair_results(rows)
        self.assertEqual(summary["rolled_back_case_count"], 1)
        self.assertEqual(summary["attempts_resolving_at_least_one_hard_failure"], 1)
        self.assertEqual(summary["attempts_rejected_by_style_gate"], 1)
        self.assertEqual(summary["hard_regression_commit_count"], 0)

    def test_blind_review_uses_strongest_rolled_back_proposal(self) -> None:
        unusable = {
            "verification": {
                "accepted": False,
                "after_usable": False,
                "introduced_hard_failures": [],
                "resolved_hard_failures": [],
                "regression_gates": {"semantic": True, "style": True},
            }
        }
        usable = {
            "verification": {
                "accepted": False,
                "after_usable": True,
                "introduced_hard_failures": [],
                "resolved_hard_failures": ["structure:lower_platform"],
                "regression_gates": {"semantic": True, "style": False},
            }
        }
        self.assertGreater(
            _attempt_review_priority(usable),
            _attempt_review_priority(unusable),
        )


if __name__ == "__main__":
    unittest.main()
