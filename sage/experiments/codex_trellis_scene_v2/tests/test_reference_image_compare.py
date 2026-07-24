from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.architecture import plan_architecture
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.reference_image_compare import (
    build_inventory_audit_prompt,
    summarize_inventory_audit,
)


class ReferenceImageComparisonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = build_baseline_brief(
            "A study with exactly one desk, one office chair, one bookcase, "
            "one cabinet, and one floor lamp."
        )
        plan_architecture(self.brief)

    def _exact_raw(self) -> dict:
        catalog = []
        for obj in self.brief["objects"]:
            if obj.get("placement_type") == "support":
                continue
            catalog.append(
                {
                    "id": obj["id"],
                    "visible_instance_count": 1,
                    "count_confidence": 0.95,
                    "observed_wall": obj.get("preferred_wall") or "interior",
                    "wall_confidence": 0.9,
                }
            )
        relations = []
        for relation in self.brief.get("relations", []):
            relations.append(
                {
                    "source": relation[0],
                    "type": relation[1],
                    "target": relation[2],
                    "satisfied": True,
                    "confidence": 0.9,
                }
            )
        return {
            "catalog": catalog,
            "relations": relations,
            "architecture": {
                "door_walls": [
                    item["wall"] for item in self.brief["architecture"]["doors"]
                ],
                "window_walls": [
                    item["wall"]
                    for item in self.brief["architecture"]["windows"]
                ],
            },
            "unexpected_objects": [],
            "warnings": [],
        }

    def test_prompt_requires_counting_extras_and_duplicates(self) -> None:
        prompt = build_inventory_audit_prompt(self.brief)
        self.assertIn("visible_instance_count", prompt)
        self.assertIn("unexpected_objects", prompt)
        self.assertIn("report count 2", prompt)
        self.assertIn("small desk lamp", prompt)

    def test_exact_inventory_passes(self) -> None:
        summary = summarize_inventory_audit(self._exact_raw(), self.brief)
        self.assertEqual(summary["metrics"]["exact_count_rate"], 1.0)
        self.assertTrue(summary["metrics"]["strict_inventory_pass"])
        self.assertTrue(summary["metrics"]["architecture_correct"])

    def test_duplicate_and_extra_furniture_fail_inventory(self) -> None:
        raw = self._exact_raw()
        raw["catalog"][0]["visible_instance_count"] = 2
        raw["unexpected_objects"] = [
            {
                "category": "drawer_chest",
                "count": 2,
                "kind": "major_furniture",
                "confidence": 0.9,
            },
            {
                "category": "plant",
                "count": 1,
                "kind": "decor",
                "confidence": 0.9,
            },
        ]
        summary = summarize_inventory_audit(raw, self.brief)
        metrics = summary["metrics"]
        self.assertFalse(metrics["strict_inventory_pass"])
        self.assertEqual(metrics["duplicate_instance_count"], 1)
        self.assertEqual(
            metrics["unexpected_object_counts"]["major_furniture"], 2
        )
        self.assertEqual(metrics["unexpected_object_counts"]["decor"], 1)


if __name__ == "__main__":
    unittest.main()
