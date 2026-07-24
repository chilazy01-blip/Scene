from __future__ import annotations

import unittest
from copy import deepcopy

from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.planner import rules_layout
from sage.experiments.codex_trellis_scene_v2.reference_soft_prior import (
    build_guided_layout_prompt,
    build_reference_prompt,
    hard_invariant_report,
    project_soft_prior,
    soft_prior_alignment,
    validate_soft_prior,
)


class ReferenceSoftPriorContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = build_baseline_brief("A study with a desk and office chair.")

    def test_reference_prompt_uses_exact_catalog_and_fixed_camera(self) -> None:
        prompt = build_reference_prompt(self.brief)
        self.assertIn("south wall", prompt)
        self.assertIn("looks due north", prompt)
        self.assertIn("Spatial contract", prompt)
        self.assertIn("doors", prompt)
        self.assertIn("windows", prompt)
        self.assertLess(len(prompt.split()), 220)
        for obj in self.brief["objects"]:
            if obj.get("placement_type") != "support":
                self.assertIn(str(obj["id"]), prompt)

    def test_unknown_and_low_confidence_observations_are_rejected(self) -> None:
        object_id = next(
            str(obj["id"])
            for obj in self.brief["objects"]
            if obj.get("placement_type") != "support"
        )
        raw = {
            "objects": [
                {
                    "id": object_id,
                    "visible": True,
                    "confidence": 0.9,
                    "bbox_normalized": [0.1, 0.2, 0.4, 0.8],
                    "room_position_hint": {
                        "x_fraction": 0.25,
                        "y_fraction": 0.75,
                        "confidence": 0.8,
                    },
                },
                {
                    "id": "hallucinated_sofa",
                    "confidence": 0.99,
                    "room_position_hint": {
                        "x_fraction": 0.5,
                        "y_fraction": 0.5,
                        "confidence": 0.9,
                    },
                },
                {
                    "id": next(
                        str(obj["id"])
                        for obj in self.brief["objects"]
                        if obj.get("placement_type") != "support"
                        and str(obj["id"]) != object_id
                    ),
                    "confidence": 0.2,
                    "room_position_hint": {
                        "x_fraction": 0.5,
                        "y_fraction": 0.5,
                        "confidence": 0.2,
                    },
                },
                {
                    "id": next(
                        str(obj["id"])
                        for obj in self.brief["objects"]
                        if obj.get("placement_type") != "support"
                        and str(obj["id"]) != object_id
                    ),
                    "confidence": 0.9,
                    "room_position_hint": {
                        "x_fraction": 0.5,
                        "y_fraction": 0.5,
                        "confidence": 0.1,
                    },
                },
            ]
        }
        prior = validate_soft_prior(raw, self.brief, minimum_confidence=0.45)
        self.assertEqual(prior["accepted_count"], 1)
        self.assertEqual(prior["accepted"][0]["id"], object_id)
        self.assertEqual(prior["accepted"][0]["strength"], "soft")
        self.assertEqual(prior["rejected_count"], 3)
        self.assertIn(
            "low_position_confidence",
            {item["reason"] for item in prior["rejected"]},
        )
        self.assertFalse(prior["contract"]["may_change_object_set"])

    def test_alignment_prefers_plan_closer_to_soft_positions(self) -> None:
        baseline = rules_layout(self.brief)
        target = next(
            obj for obj in baseline["objects"] if obj.get("placement_type") == "floor"
        )
        prior = {
            "accepted": [
                {
                    "id": target["id"],
                    "confidence": 1.0,
                    "room_position_hint": {
                        "x_fraction": 0.1,
                        "y_fraction": 0.1,
                        "confidence": 1.0,
                    },
                }
            ]
        }
        guided = deepcopy(baseline)
        guided_target = next(
            obj for obj in guided["objects"] if obj["id"] == target["id"]
        )
        guided_target["x"] = 0.1 * float(guided["room"]["width"])
        guided_target["y"] = 0.1 * float(guided["room"]["length"])
        baseline_score = soft_prior_alignment(baseline, prior)
        guided_score = soft_prior_alignment(guided, prior)
        self.assertGreater(
            baseline_score["weighted_normalized_rmse"],
            guided_score["weighted_normalized_rmse"],
        )

    def test_hard_invariants_reject_dimension_changes(self) -> None:
        baseline = rules_layout(self.brief)
        guided = deepcopy(baseline)
        guided["objects"][0]["dimensions"]["width"] *= 0.5
        report = hard_invariant_report(self.brief, baseline, guided)
        self.assertFalse(report["ok"])
        self.assertFalse(report["checks"]["dimensions_unchanged"])

    def test_guided_prompt_declares_soft_authority(self) -> None:
        baseline = rules_layout(self.brief)
        prior = {
            "schema": "codex_trellis_reference_soft_layout_prior_v1",
            "accepted_count": 0,
            "accepted": [],
        }
        prompt = build_guided_layout_prompt(self.brief, baseline, prior)
        self.assertIn("SOFT suggestions only", prompt)
        self.assertIn("always win", prompt)
        self.assertIn("Keep changes from the baseline minimal", prompt)

    def test_projection_moves_wall_objects_only_along_wall(self) -> None:
        baseline = rules_layout(self.brief)
        target = next(
            obj
            for obj in baseline["objects"]
            if obj.get("preferred_wall") in {"north", "south"}
        )
        prior = {
            "schema": "codex_trellis_reference_soft_layout_prior_v1",
            "accepted_count": 1,
            "accepted": [
                {
                    "id": target["id"],
                    "confidence": 1.0,
                    "room_position_hint": {
                        "x_fraction": 0.75,
                        "y_fraction": 0.2,
                        "confidence": 1.0,
                    },
                }
            ],
        }
        projected, audit = project_soft_prior(baseline, prior, self.brief)
        before = next(obj for obj in baseline["objects"] if obj["id"] == target["id"])
        after = next(obj for obj in projected["objects"] if obj["id"] == target["id"])
        self.assertAlmostEqual(float(before["y"]), float(after["y"]))
        self.assertTrue(audit["attempted_candidates"] > 0)
        self.assertEqual(
            set(obj["id"] for obj in baseline["objects"]),
            set(obj["id"] for obj in projected["objects"]),
        )


if __name__ == "__main__":
    unittest.main()
