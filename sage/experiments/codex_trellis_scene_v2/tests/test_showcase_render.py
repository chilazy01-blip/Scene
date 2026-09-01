from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from sage.experiments.codex_trellis_scene_v2.showcase_render import (
    RENDER_PROFILES,
    evaluate_showcase_quality,
    score_camera_candidate,
    select_camera_pair,
    validate_render_profiles,
)


class ShowcaseRenderTest(unittest.TestCase):
    def test_profiles_are_distinct_and_production_fixed(self) -> None:
        result = validate_render_profiles(RENDER_PROFILES)
        self.assertTrue(result["ok"])
        self.assertEqual(RENDER_PROFILES["final_showcase"]["engine"], "CYCLES")
        self.assertTrue(RENDER_PROFILES["final_showcase"]["denoise"])

    def test_camera_score_penalizes_crop_and_rewards_relations(self) -> None:
        candidate = {
            "objects": {
                "chair": {
                    "visible_pixels": 100,
                    "projection_inside_frame": True,
                    "touches_image_border": False,
                },
                "desk": {
                    "visible_pixels": 100,
                    "projection_inside_frame": False,
                    "touches_image_border": True,
                },
            },
            "scene_occupancy_fraction": 0.55,
            "visible_centroid_centeredness": 0.9,
        }
        score = score_camera_candidate(
            candidate,
            required_object_ids={"chair", "desk"},
            relation_pairs=[("chair", "desk")],
        )
        self.assertEqual(score["required_coverage"], 1.0)
        self.assertEqual(score["relation_coverage"], 1.0)
        self.assertEqual(score["cropped_required_ids"], ["desk"])

    def test_pair_selection_uses_complementary_views(self) -> None:
        def candidate(name: str, side: str, visible: set[str]) -> dict:
            return {
                "id": name,
                "room_side": side,
                "objects": {
                    object_id: {
                        "visible_pixels": 100 if object_id in visible else 0,
                        "projection_inside_frame": True,
                        "touches_image_border": False,
                    }
                    for object_id in {"a", "b", "c"}
                },
                "scene_occupancy_fraction": 0.55,
                "visible_centroid_centeredness": 1.0,
            }

        selection = select_camera_pair(
            [
                candidate("south", "south", {"a", "b"}),
                candidate("north", "north", {"b", "c"}),
                candidate("south_duplicate", "south", {"a", "b"}),
            ],
            required_object_ids={"a", "b", "c"},
            relation_pairs=[("a", "b"), ("b", "c")],
        )
        self.assertEqual(selection["pair_objective"]["required_coverage"], 1.0)
        self.assertEqual(selection["pair_objective"]["relation_coverage"], 1.0)
        self.assertTrue(selection["pair_objective"]["different_room_side"])

    def test_quality_gate_rejects_white_and_cropped_frame(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "white.png"
            Image.fromarray(np.full((64, 64, 3), 255, dtype=np.uint8)).save(path)
            report = evaluate_showcase_quality(
                {
                    "profiles": RENDER_PROFILES,
                    "selected_views": [
                        {
                            "id": "hero",
                            "rgb_path": str(path),
                            "cropped_required_ids": ["wardrobe"],
                        }
                    ],
                    "camera_selection": {
                        "pair_objective": {
                            "required_coverage": 1.0,
                            "relation_coverage": 1.0,
                        }
                    },
                }
            )
        self.assertFalse(report["ok"])
        self.assertIn("overexposure", {item["type"] for item in report["failures"]})
        self.assertIn(
            "required_object_cropped", {item["type"] for item in report["failures"]}
        )

    def test_quality_gate_rejects_pure_black_visible_window(self) -> None:
        with TemporaryDirectory() as directory:
            directory_path = Path(directory)
            rgb_path = directory_path / "rgb.png"
            mask_path = directory_path / "mask.png"
            rgb = np.full((64, 64, 3), 128, dtype=np.uint8)
            rgb[16:48, 16:48] = 0
            mask = np.zeros((64, 64), dtype=np.uint8)
            mask[16:48, 16:48] = 128
            Image.fromarray(rgb).save(rgb_path)
            Image.fromarray(mask).save(mask_path)
            report = evaluate_showcase_quality(
                {
                    "profiles": RENDER_PROFILES,
                    "selected_views": [
                        {
                            "id": "window_view",
                            "rgb_path": str(rgb_path),
                            "cropped_required_ids": [],
                            "object_index_mask_path": str(mask_path),
                            "object_index_denominator": 2,
                            "object_mask_observations": {
                                "window_main": {"pass_index": 1, "visible_pixels": 1024}
                            },
                        }
                    ],
                    "camera_selection": {
                        "selected_candidate_ids": ["window_view"],
                        "pair_objective": {
                            "required_coverage": 1.0,
                            "relation_coverage": 1.0,
                        },
                    },
                }
            )
        self.assertFalse(report["ok"])
        self.assertIn(
            "pure_black_window", {item["type"] for item in report["failures"]}
        )


if __name__ == "__main__":
    unittest.main()
