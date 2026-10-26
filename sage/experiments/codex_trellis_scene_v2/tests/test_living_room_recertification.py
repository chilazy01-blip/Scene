from __future__ import annotations

import unittest

from sage.experiments.codex_trellis_scene_v2.build_living_room_recertification import (
    _asset_family_by_category,
)
from sage.experiments.codex_trellis_scene_v2.render_collision_relationship_result import (
    _boxes_overlap,
    _place_label_box,
)


class LivingRoomRecertificationTests(unittest.TestCase):
    def test_asset_family_gate_requires_all_categories_and_fit_passes(self) -> None:
        categories = (
            "sofa", "coffee_table", "tv_stand", "tv", "accent_chair",
            "side_table", "floor_lamp", "bookcase",
        )
        report = {
            "ok": True,
            "assets": [
                {"asset_id": f"{category}_001", "category": category, "fit_audit": {"ok": True}}
                for category in categories
            ],
        }
        self.assertEqual(set(_asset_family_by_category(report)), set(categories))
        report["assets"][0]["fit_audit"]["ok"] = False
        with self.assertRaises(RuntimeError):
            _asset_family_by_category(report)

    def test_dense_map_label_placement_avoids_existing_label(self) -> None:
        occupied = [(80.0, 80.0, 140.0, 104.0)]
        placed = _place_label_box(
            (110.0, 92.0),
            (52.0, 16.0),
            occupied,
            (0.0, 0.0, 240.0, 180.0),
        )
        self.assertFalse(_boxes_overlap(occupied[0], placed))
        self.assertGreaterEqual(placed[0], 0.0)
        self.assertLessEqual(placed[2], 240.0)


if __name__ == "__main__":
    unittest.main()
