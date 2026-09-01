from __future__ import annotations

import unittest

from ..scene_dna_feasibility import assess_3d_feasibility, select_3d_candidate


def _report(*, hard: bool, score: float, platform: bool = False) -> dict:
    return {
        "evaluated": True,
        "rendered_view_count": 4,
        "missing_views": [],
        "hard_geometry_gate_passed": hard,
        "automated_pixel_multiview_pass": hard and score >= 0.55,
        "automated_score": score,
        "structure_gate": {
            "basic_foreground_passed": True,
            "general_fragment_passed": True,
            "compact_silhouette_passed": True,
            "internal_hole_passed": True,
            "lower_overhang_passed": True,
            "lower_platform_passed": not platform,
        },
        "opposite_view_consistency": {
            "passes": hard,
            "minimum_pair_score": 0.9 if hard else 0.3,
        },
        "scale_anisotropy_gate": {"passes": True, "actual": 1.2},
    }


class SceneDNAFeasibilityTest(unittest.TestCase):
    def test_assessment_reports_generic_platform_failure(self) -> None:
        assessment = assess_3d_feasibility(
            _report(hard=False, score=0.9, platform=True)
        )
        self.assertFalse(assessment["usable_for_scene_assembly"])
        self.assertIn("structure:lower_platform", assessment["hard_failures"])
        self.assertFalse(assessment["category_specific_branching"])

    def test_hard_geometry_beats_higher_soft_score(self) -> None:
        bad = {
            "attempt": 0,
            "candidate_rank": 1,
            "path": "bad.glb",
            "multiview": _report(hard=False, score=0.95, platform=True),
        }
        good = {
            "attempt": 0,
            "candidate_rank": 2,
            "path": "good.glb",
            "multiview": _report(hard=True, score=0.60),
        }
        selected, decision = select_3d_candidate([bad, good])
        self.assertEqual(selected["path"], "good.glb")
        self.assertTrue(decision["usable_for_scene_assembly"])

    def test_all_hard_failures_are_rejected_not_assembled(self) -> None:
        candidates = [
            {
                "attempt": 0,
                "candidate_rank": rank,
                "path": f"bad-{rank}.glb",
                "multiview": _report(
                    hard=False, score=0.9 - rank * 0.1, platform=True
                ),
            }
            for rank in (1, 2)
        ]
        _, decision = select_3d_candidate(candidates)
        self.assertFalse(decision["usable_for_scene_assembly"])
        self.assertTrue(decision["best_of_failures_must_not_enter_scene"])
        self.assertEqual(
            decision["action"],
            "reject_batch_and_regenerate_without_assembling_best_failure",
        )

    def test_unevaluated_candidate_can_only_pass_explicit_legacy_mode(self) -> None:
        candidate = {"path": "legacy.glb", "multiview": None}
        _, strict = select_3d_candidate([candidate])
        _, legacy = select_3d_candidate([candidate], require_hard_geometry=False)
        self.assertFalse(strict["usable_for_scene_assembly"])
        self.assertTrue(legacy["usable_for_scene_assembly"])

    def test_corrupt_legacy_pass_flag_cannot_outrank_hard_usable_candidate(self) -> None:
        inconsistent = _report(hard=False, score=0.99, platform=True)
        inconsistent["automated_pixel_multiview_pass"] = True
        selected, decision = select_3d_candidate(
            [
                {"path": "corrupt.glb", "multiview": inconsistent},
                {"path": "usable.glb", "multiview": _report(hard=True, score=0.60)},
            ]
        )
        self.assertEqual(selected["path"], "usable.glb")
        self.assertTrue(decision["usable_for_scene_assembly"])
