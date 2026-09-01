from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.scene_dna_effectiveness import (
    compare_effectiveness,
)


def _report(
    score: float,
    *,
    passed: bool = True,
    structure: bool = True,
    scale: bool = True,
) -> dict:
    return {
        "evaluated": True,
        "automated_pixel_multiview_pass": passed,
        "acceptance": "pass" if passed else "fail",
        "automated_score": score,
        "mean_style_score": score - 0.05,
        "minimum_view_style_score": score - 0.08,
        "structure_gate_passed": structure,
        "structure_gate": {"compact_silhouette_passed": structure},
        "reference_appearance": {"score": 0.8},
        "opposite_view_consistency": {"minimum_pair_score": 0.9, "passes": True},
        "normalization": {"axis_scale_anisotropy": 1.2},
        "scale_anisotropy_gate": {"passes": scale},
    }


class SceneDNAEffectivenessTest(unittest.TestCase):
    def test_compare_effectiveness_detects_positive_score_effect(self) -> None:
        comparison = compare_effectiveness(_report(0.70), _report(0.74))
        self.assertEqual(comparison["automated_verdict"], "positive_effect")
        self.assertEqual(
            comparison["deltas_selected_minus_baseline"]["automated_score"],
            0.04,
        )
        self.assertTrue(comparison["semantic_review_required"])

    def test_compare_effectiveness_prioritizes_pass_transition(self) -> None:
        comparison = compare_effectiveness(
            _report(0.80, passed=False), _report(0.79, passed=True)
        )
        self.assertEqual(comparison["automated_verdict"], "positive_effect")

    def test_compare_effectiveness_calls_small_delta_inconclusive(self) -> None:
        comparison = compare_effectiveness(_report(0.70), _report(0.71))
        self.assertEqual(
            comparison["automated_verdict"], "inconclusive_or_small_effect"
        )

    def test_compare_effectiveness_does_not_call_two_hard_failures_positive(self) -> None:
        comparison = compare_effectiveness(
            _report(0.70, passed=False, structure=False),
            _report(0.78, passed=False, scale=False),
        )
        self.assertEqual(
            comparison["automated_verdict"], "both_failed_hard_geometry"
        )
