from __future__ import annotations

import unittest

import numpy as np

from sage.experiments.codex_trellis_scene_v2.scene_delivery_optimization import choose_target_faces, mask_iou


class SceneDeliveryOptimizationTests(unittest.TestCase):
    def test_category_and_complexity_change_budget(self) -> None:
        boxy_books = choose_target_faces("book_row", 500_000, curvature=0.05, silhouette=0.1)
        curved_chair = choose_target_faces("office_chair", 500_000, curvature=0.9, silhouette=0.8)
        self.assertLess(boxy_books, curved_chair)
        self.assertLess(boxy_books, 60_000)

    def test_small_mesh_is_not_needlessly_decimated(self) -> None:
        self.assertEqual(
            choose_target_faces("architecture", 12, curvature=0.0, silhouette=0.0),
            12,
        )

    def test_target_never_exceeds_source(self) -> None:
        self.assertEqual(
            choose_target_faces("office_chair", 2_500, curvature=1.0, silhouette=1.0),
            2_500,
        )

    def test_mask_iou_is_exact(self) -> None:
        first = np.asarray([[True, True], [False, False]])
        second = np.asarray([[True, False], [True, False]])
        iou, intersection, union = mask_iou(first, second)
        self.assertEqual((intersection, union), (1, 3))
        self.assertAlmostEqual(iou, 1 / 3)


if __name__ == "__main__":
    unittest.main()
