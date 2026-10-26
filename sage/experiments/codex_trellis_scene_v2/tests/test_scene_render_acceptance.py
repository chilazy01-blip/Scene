from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from ..scene_render_acceptance import evaluate_scene_render_manifest


class SceneRenderAcceptanceTest(unittest.TestCase):
    def test_native_integer_ids_do_not_round_fractional_boundary_colors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest,plan=self._fixture(Path(tmp), visible=True)
            for view in manifest['qa_passes']['views'].values():
                Path(view['objects']['chair']['mask_path']).unlink()
                index=Path(tmp)/'index.png'
                Image.fromarray(np.full((64,64),64,dtype=np.uint8)).save(index)
                view.update(object_index_path=str(index),object_index_denominator=2,
                    object_index_max_pixel_value=255,object_index_encoding='native_integer_ids')
                view['objects']['chair'].update(pass_index=1)
            with self.assertRaises(ValueError):
                evaluate_scene_render_manifest(manifest,plan)

    def _fixture(self, root: Path, *, visible: bool = True) -> tuple[dict, dict]:
        views = {}
        for view in ("top", "corner", "front"):
            rgb = root / f"{view}_rgb.png"
            depth = root / f"{view}_depth.png"
            mask = root / f"{view}_chair.png"
            Image.new("RGB", (64, 64), "gray").save(rgb)
            depth_array = np.zeros((64, 64), dtype=np.uint16)
            depth_array[10:54, 10:54] = 32000
            Image.fromarray(depth_array).save(depth)
            mask_array = np.zeros((64, 64), dtype=np.uint8)
            if visible:
                mask_array[20:48, 18:46] = 255
            Image.fromarray(mask_array, mode="L").save(mask)
            views[view] = {
                "rgb_path": str(rgb),
                "depth_path": str(depth),
                "objects": {
                    "chair": {
                        "mask_path": str(mask),
                        "projection": {
                            "matched_mesh_count": 2,
                            "projected_bbox_area_pixels": 1200,
                            "bbox_inside_frame": True,
                        },
                    }
                },
            }
        return (
            {"qa_passes": {"enabled": True, "views": views}},
            {
                "objects": [{"id": "chair", "category": "office_chair", "required": True}],
                "camera_requirements": {"complete_required_objects_visible": True},
            },
        )

    def test_accepts_visible_required_object_with_rgb_depth_and_masks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, plan = self._fixture(Path(tmp), visible=True)
            report = evaluate_scene_render_manifest(manifest, plan)
        self.assertTrue(report["accepted"], report)
        self.assertEqual(report["visible_required_object_count"], 1)
        self.assertEqual(report["complete_required_object_count"], 1)

    def test_rejects_required_object_missing_from_all_visible_masks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, plan = self._fixture(Path(tmp), visible=False)
            report = evaluate_scene_render_manifest(manifest, plan)
        self.assertFalse(report["accepted"])
        self.assertIn(
            "required_object_not_visibly_rendered",
            {item["type"] for item in report["hard_failures"]},
        )

    def test_rejects_missing_depth_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest, plan = self._fixture(Path(tmp), visible=True)
            Path(manifest["qa_passes"]["views"]["front"]["depth_path"]).unlink()
            report = evaluate_scene_render_manifest(manifest, plan)
        self.assertFalse(report["accepted"])
        self.assertIn(
            "missing_or_flat_depth",
            {item["type"] for item in report["hard_failures"]},
        )

    def test_decodes_shared_eight_bit_object_index_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rgb = root / "rgb.png"
            depth = root / "depth.png"
            index = root / "index.png"
            Image.new("RGB", (64, 64), "gray").save(rgb)
            depth_array = np.zeros((64, 64), dtype=np.uint16)
            depth_array[8:56, 8:56] = 32000
            Image.fromarray(depth_array).save(depth)
            index_array = np.zeros((64, 64), dtype=np.uint8)
            index_array[18:50, 18:50] = 128
            Image.fromarray(index_array).save(index)
            manifest = {
                "qa_passes": {
                    "views": {
                        "front": {
                            "rgb_path": str(rgb),
                            "depth_path": str(depth),
                            "object_index_path": str(index),
                            "object_index_denominator": 2,
                            "object_index_max_pixel_value": 255,
                            "object_index_transfer": "linear",
                            "objects": {
                                "chair": {
                                    "pass_index": 1,
                                    "projection": {
                                        "matched_mesh_count": 1,
                                        "projected_bbox_area_pixels": 1400,
                                        "bbox_inside_frame": True,
                                    },
                                }
                            },
                        }
                    }
                }
            }
            plan = {"objects": [{"id": "chair", "required": True}]}
            report = evaluate_scene_render_manifest(manifest, plan)
        self.assertTrue(report["accepted"], report)
        self.assertGreater(report["objects"]["chair"]["best_observation"]["visible_pixels"], 1000)
