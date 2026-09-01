from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sage.experiments.codex_trellis_scene_v2 import build_sdf_complex_bedroom as build
from sage.experiments.codex_trellis_scene_v2.content_chain import (
    build_generation_contract,
    make_artifact_certificate,
)


def healthy_checkpoint() -> dict[str, object]:
    return {
        "healthy_for_heavy_stage": True,
        "metrics": {
            "mem_available_gib": 200.0,
            "dirty_writeback_gib": 0.0,
            "blocked_processes_before": 0,
            "blocked_processes_after": 0,
            "iowait_fraction": 0.0,
        },
    }


class SdfBedroomRunnerTest(unittest.TestCase):
    def _qa_row(self, root: Path, asset_id: str) -> dict[str, object]:
        glb = root / f"{asset_id}.glb"
        glb.write_bytes(f"approved:{asset_id}".encode("utf-8"))
        sheet = root / "evidence" / f"{asset_id}.png"
        sheet.parent.mkdir(exist_ok=True)
        sheet.write_bytes(f"sheet:{asset_id}".encode("utf-8"))
        views = {}
        evidence = {"contact_sheet": sheet}
        for view_name in ("front", "back", "left", "right"):
            view = root / "evidence" / f"{asset_id}_{view_name}.png"
            view.write_bytes(f"{view_name}:{asset_id}".encode("utf-8"))
            views[view_name] = f"evidence/{asset_id}_{view_name}.png"
            evidence[f"view_{view_name}"] = view
        contract = build_generation_contract(
            category="book_stack",
            prompt=f"one isolated {asset_id}",
            target_dimensions_m={"width": 0.5, "length": 0.2, "height": 0.3},
            seed=42,
            model_fingerprint="model-a",
            rmbg_fingerprint="rmbg-a",
            pipeline_type="512",
            steps=12,
            texture_size=1024,
            decimation_target=200000,
            preprocess_image=True,
            code_version="commit-a",
        )
        rules = {
            "renderer_binary": {"sha256": "blender-binary-a"},
            "renderer_script": {"sha256": "turntable-script-a"},
            "camera_contract": "turntable-4-view-v1",
            "qa_rules_version": "trellis-multiview-v2",
        }
        return {
            "asset_id": asset_id,
            "accepted": True,
            "glb_sha256": build.sha256_file(glb),
            "contact_sheet": f"evidence/{asset_id}.png",
            "contact_sheet_sha256": build.sha256_file(sheet),
            "views": views,
            "generation_contract": contract,
            "qa_rules": rules,
            "content_certificate": make_artifact_certificate(
                glb,
                upstream={"generation_contract": contract},
                rules=rules,
                evidence=evidence,
            ),
        }

    def test_geometry_assets_are_six_isolated_units(self) -> None:
        self.assertEqual(len(build.GEOMETRY_ASSET_IDS), 6)
        self.assertEqual(len(set(build.GEOMETRY_ASSET_IDS)), 6)
        self.assertIn("office_chair_black_mesh_001", build.GEOMETRY_ASSET_IDS)
        self.assertIn("open_bookcase_trellis2_001", build.GEOMETRY_ASSET_IDS)
        self.assertFalse(
            any("parametric" in asset_id for asset_id in build.GEOMETRY_ASSET_IDS)
        )

    def test_multiview_gate_requires_every_trellis_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "multiview_qa.json").write_text(
                json.dumps(
                    {
                        "schema": "codex_trellis_multiview_qa_v2",
                        "ok": True,
                        "assets": [
                            {"asset_id": asset_id, "accepted": True}
                            for asset_id in build.TRELLIS_ASSET_INDEX
                            if asset_id != "book_row_trellis2_003"
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "book_row_trellis2_003"):
                build._require_trellis_multiview_qa(root)

    def test_multiview_gate_accepts_all_real_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [self._qa_row(root, asset_id) for asset_id in build.TRELLIS_ASSET_INDEX]
            payload = {
                "schema": "codex_trellis_multiview_qa_v2",
                "ok": True,
                "assets": rows,
            }
            (root / "multiview_qa.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            self.assertEqual(build._require_trellis_multiview_qa(root), payload)

    def test_multiview_gate_rejects_glb_replaced_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [self._qa_row(root, asset_id) for asset_id in build.TRELLIS_ASSET_INDEX]
            (root / "multiview_qa.json").write_text(
                json.dumps(
                    {
                        "schema": "codex_trellis_multiview_qa_v2",
                        "ok": True,
                        "assets": rows,
                    }
                ),
                encoding="utf-8",
            )
            changed = next(iter(build.TRELLIS_ASSET_INDEX))
            (root / f"{changed}.glb").write_bytes(b"replaced-after-review")
            with self.assertRaisesRegex(RuntimeError, "GLB hash mismatch"):
                build._require_trellis_multiview_qa(root)

    def test_inherited_scene_contract_repair_restores_shoes_and_wardrobe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            asset_root = Path(temporary)
            (asset_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "asset_id": "slipper_blue_left_001",
                                "asset_axis_to_z": 2,
                                "asset_local_yaw_offset_degrees": 0,
                                "asset_canonical_front": {
                                    "axis": "+x",
                                    "confidence": 0.9,
                                },
                                "asset_medial_axis": {
                                    "axis": "+y",
                                    "confidence": 0.9,
                                },
                                "pair_role": "right",
                                "pair_role_semantics": "anatomical_wearer",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            plan = {
                "description": "Place one matched pair of slippers near the foot of the bed.",
                "room": {"width": 5.2, "length": 4.4, "height": 2.7},
                "room_type": "bedroom",
                "architecture": {
                    "walls": ["north", "south", "east", "west"],
                    "requirements": {
                        "enclosing_wall_count": 4,
                        "door_count": 1,
                        "window_count_min": 1,
                        "window_count_max": 1,
                        "floor_material_required": True,
                        "wall_material_required": True,
                    },
                    "doors": [
                        {
                            "id": "entry_door",
                            "wall": "east",
                            "center": 0.7,
                            "width": 0.9,
                            "height": 2.1,
                            "clearance_depth": 1.0,
                        }
                    ],
                    "windows": [
                        {
                            "id": "window_main",
                            "wall": "west",
                            "center": 3.2,
                            "width": 1.0,
                            "height": 1.0,
                            "sill_height": 1.0,
                        }
                    ],
                    "floor": {
                        "id": "floor",
                        "material": {
                            "material_id": "wood",
                            "texture_type": "procedural",
                        },
                    },
                    "wall_finish": {
                        "default": {
                            "material_id": "plaster",
                            "texture_type": "procedural",
                        },
                        "overrides": {},
                    },
                },
                "object_budget": {
                    "required_object_ids": [
                        "bed",
                        "wardrobe",
                        "explicit_slipper_1",
                        "explicit_slipper_2",
                    ]
                },
                "objects": [
                    {
                        "id": "bed",
                        "category": "bed",
                        "x": 2.6,
                        "y": 3.27,
                        "yaw": 0,
                        "dimensions": {"width": 1.8, "length": 2.1, "height": 1.05},
                        "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
                    },
                    {
                        "id": "wardrobe",
                        "category": "wardrobe",
                        "x": 0.39,
                        "y": 0.88,
                        "yaw": 270,
                        "preferred_wall": "east",
                        "wall_constraint_strength": "soft",
                        "facing_constraint": {
                            "mode": "into_room",
                            "wall": "east",
                            "local_front_fallback": "-y",
                            "tolerance_degrees": 15,
                        },
                        "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
                        "dimensions": {"width": 1.6, "length": 0.62, "height": 2.1},
                    },
                    {
                        "id": "explicit_area_rug",
                        "category": "area_rug",
                        "x": 2.6,
                        "y": 2.85,
                        "yaw": 0,
                        "dimensions": {"width": 2.4, "length": 1.7, "height": 0.02},
                    },
                    *[
                        {
                            "id": f"explicit_slipper_{index}",
                            "category": "slipper",
                            "provenance": "user_explicit",
                            "asset_id": "slipper_blue_left_001",
                            "asset_source": "curated_library",
                            "instance_group_id": "explicit_slipper_pair",
                            "x": x,
                            "y": 1.76,
                            "yaw": 0,
                            "dimensions": {"width": 0.28, "length": 0.12, "height": 0.08},
                        }
                        for index, x in ((1, 2.42), (2, 2.78))
                    ],
                ],
                "instance_groups": [],
                "relations": [],
                "orientation_resolution": [],
            }

            report = build._repair_inherited_scene_contracts(plan, asset_root)
            by_id = {item["id"]: item for item in plan["objects"]}

            self.assertTrue(report["ok"])
            self.assertEqual(by_id["wardrobe"]["preferred_wall"], "west")
            self.assertEqual(by_id["wardrobe"]["yaw"], 90.0)
            self.assertEqual(len(plan["instance_groups"]), 1)
            self.assertEqual(plan["instance_group_resolution"]["group_count"], 1)
            self.assertEqual(by_id["explicit_slipper_1"]["yaw"], 270.0)
            self.assertEqual(by_id["explicit_slipper_2"]["yaw"], 270.0)
            self.assertAlmostEqual(by_id["explicit_slipper_1"]["x"], 2.7)
            self.assertAlmostEqual(by_id["explicit_slipper_2"]["x"], 2.5)
            self.assertEqual(by_id["explicit_slipper_1"]["asset_reflection_axis"], "y")
            self.assertNotIn("asset_reflection_axis", by_id["explicit_slipper_2"])
            self.assertTrue(
                report["whole_scene_pre_geometry_audit"]["instance_groups"]["results"][0][
                    "handedness_verified"
                ]
            )

    def test_layout_yaw_is_converted_to_relation_pose_contract(self) -> None:
        pose = build._layout_pose({"x": 1, "y": 2, "z": 3, "yaw": 270})
        self.assertEqual(pose["yaw_degrees"], 270.0)
        matrix = build.pose_matrix(pose)
        self.assertAlmostEqual(float(matrix[0, 1]), 1.0)
        self.assertAlmostEqual(float(matrix[1, 0]), -1.0)

    def test_monitored_child_writes_success_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(
                build, "append_health_checkpoint", return_value=healthy_checkpoint()
            ):
                report = build._run_monitored_subprocess(
                    [sys.executable, "-c", "print('ok')"],
                    output=root,
                    stage="synthetic_success",
                    log_path=root / "logs" / "success.log",
                    checkpoint_path=root / "checkpoints" / "success.exit.json",
                    monitor_interval_seconds=0.01,
                )
            stored = json.loads(
                (root / "checkpoints" / "success.exit.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(report["ok"])
            self.assertTrue(stored["ok"])
            self.assertEqual(stored["exit_code"], 0)
            self.assertIn("last_rss_gib", stored)

    def test_monitored_child_writes_failure_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(
                build, "append_health_checkpoint", return_value=healthy_checkpoint()
            ):
                with self.assertRaises(RuntimeError):
                    build._run_monitored_subprocess(
                        [sys.executable, "-c", "raise SystemExit(7)"],
                        output=root,
                        stage="synthetic_failure",
                        log_path=root / "logs" / "failure.log",
                        checkpoint_path=root / "checkpoints" / "failure.exit.json",
                        monitor_interval_seconds=0.01,
                    )
            stored = json.loads(
                (root / "checkpoints" / "failure.exit.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(stored["ok"])
            self.assertEqual(stored["exit_code"], 7)
            self.assertIsNone(stored["signal"])


if __name__ == "__main__":
    unittest.main()
