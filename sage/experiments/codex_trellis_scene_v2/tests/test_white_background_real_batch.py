from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from sage.experiments.codex_trellis_scene_v2.white_background_real_batch import (
    _alpha_metrics,
    frozen_cases,
)


class WhiteBackgroundRealBatchTests(unittest.TestCase):
    def test_batch_is_four_categories_two_unique_seeds_each(self) -> None:
        cases = frozen_cases()
        self.assertEqual(len(cases), 8)
        self.assertEqual(len({case["seed"] for case in cases}), 8)
        by_category: dict[str, int] = {}
        for case in cases:
            by_category[case["category"]] = by_category.get(case["category"], 0) + 1
        self.assertEqual(
            by_category,
            {"sofa": 2, "accent_chair": 2, "dining_chair": 2, "office_chair": 2},
        )

    def test_low_view_metrics_expose_full_width_lower_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "platform.png"
            image = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((25, 25, 102, 84), fill=(180, 170, 160, 255))
            draw.rectangle((15, 85, 112, 103), fill=(40, 40, 40, 255))
            image.save(path)
            metrics = _alpha_metrics(path)
        self.assertTrue(metrics["ok"])
        self.assertEqual(metrics["lower_maximum_row_occupancy"], 1.0)
        self.assertGreater(metrics["lower_full_width_row_fraction"], 0.4)


if __name__ == "__main__":
    unittest.main()
