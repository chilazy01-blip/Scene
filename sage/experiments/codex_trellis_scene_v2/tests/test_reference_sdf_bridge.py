from __future__ import annotations

import unittest
from pathlib import Path

from sage.experiments.codex_trellis_scene_v2.architecture import plan_architecture
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.io_utils import read_json
from sage.experiments.codex_trellis_scene_v2.planner import rules_layout
from sage.experiments.codex_trellis_scene_v2.reference_sdf_bridge import (
    REFERENCE_SDF_BINDING_SCHEMA,
    _relation_aware_validation,
    derive_tucked_under_reference_target,
    target_local_to_world,
    validate_binding_contract,
    world_to_target_local,
)
from sage.experiments.codex_trellis_scene_v2.reference_soft_prior import (
    build_parser,
)
from sage.experiments.codex_trellis_scene_v2.scene_graph import (
    build_typed_scene_graph,
)


class ReferenceSdfBridgeTest(unittest.TestCase):
    def _brief_and_plan(self):
        brief = build_baseline_brief("A study with a desk and office chair.")
        brief["relations"].append(
            {
                "source": "office_chair",
                "type": "tucked_under",
                "target": "desk",
                "strength": "hard",
                "parameters": {
                    "free_space_id": "under_desk",
                    "reference_frame": "target_local",
                    "preserve_facing": True,
                },
            }
        )
        brief["scene_graph"] = build_typed_scene_graph(
            brief, plan_architecture(brief)
        )
        return brief, rules_layout(brief)

    def test_world_local_roundtrip_respects_target_yaw(self) -> None:
        target = {"x": 2.0, "y": 3.0, "z": 0.2, "yaw": 90.0}
        world = {"x": 2.5, "y": 3.2, "z": 0.4, "yaw": 270.0}
        local = world_to_target_local(world, target)
        restored = target_local_to_world(local, target)
        for key in ("x", "y", "z", "yaw"):
            self.assertAlmostEqual(restored[key], world[key], places=7)

    def test_checked_binding_contract_is_valid(self) -> None:
        binding = {
            "schema": REFERENCE_SDF_BINDING_SCHEMA,
            "relations": [
                {
                    "source_object_id": "office_chair",
                    "relation_type": "tucked_under",
                    "target_object_id": "desk",
                    "source_asset_id": "office_chair_black_mesh_001",
                    "target_asset_id": "desk_warm_oak_001",
                    "free_space_id": "under_desk",
                }
            ],
        }
        self.assertTrue(validate_binding_contract(binding)["ok"])
        checked_path = (
            Path(__file__).resolve().parents[1]
            / "capabilities"
            / "pilot_reference_sdf_binding_v1.json"
        )
        self.assertTrue(validate_binding_contract(read_json(checked_path))["ok"])

    def test_two_image_observations_become_target_local_soft_pose(self) -> None:
        brief, plan = self._brief_and_plan()
        desk = next(obj for obj in plan["objects"] if obj["id"] == "desk")
        chair = next(
            obj for obj in plan["objects"] if obj["id"] == "office_chair"
        )
        prior = {
            "accepted": [
                {
                    "id": "office_chair",
                    "confidence": 0.9,
                    "room_position_hint": {
                        "x_fraction": 0.55,
                        "y_fraction": 0.70,
                        "confidence": 0.8,
                    },
                },
                {
                    "id": "desk",
                    "confidence": 0.95,
                    "room_position_hint": {
                        "x_fraction": 0.50,
                        "y_fraction": 0.89,
                        "confidence": 0.9,
                    },
                },
            ]
        }
        relation = next(
            item
            for item in plan["relations"]
            if isinstance(item, dict) and item.get("type") == "tucked_under"
        )
        free_space = {
            "entry_pose": {
                "yaw_degrees": 180.0,
            }
        }
        result = derive_tucked_under_reference_target(
            plan, prior, relation, free_space
        )
        observed_dx = (
            0.55 - 0.50
        ) * float(plan["room"]["width"])
        observed_dy = (
            0.70 - 0.89
        ) * float(plan["room"]["length"])
        expected_world = {
            "x": float(desk["x"]) + observed_dx,
            "y": float(desk["y"]) + observed_dy,
            "z": float(chair["z"]),
            "yaw": float(chair["yaw"]),
        }
        expected_local = world_to_target_local(
            expected_world,
            {
                "x": float(desk["x"]),
                "y": float(desk["y"]),
                "z": float(desk["z"]),
                "yaw": float(desk["yaw"]),
            },
        )
        self.assertAlmostEqual(
            result["translation_m"][0], expected_local["x"]
        )
        self.assertAlmostEqual(
            result["translation_m"][1], expected_local["y"]
        )
        self.assertEqual(result["yaw_degrees"], 180.0)
        self.assertAlmostEqual(result["confidence"], 0.72)
        self.assertEqual(
            result["position_source"],
            "source_and_target_image_observations",
        )

    def test_only_bound_pair_aabb_collision_can_be_waived(self) -> None:
        _, plan = self._brief_and_plan()
        desk = next(obj for obj in plan["objects"] if obj["id"] == "desk")
        chair = next(
            obj for obj in plan["objects"] if obj["id"] == "office_chair"
        )
        chair.update(
            {
                "x": float(desk["x"]),
                "y": float(desk["y"]) - 0.53,
                "yaw": 180.0,
            }
        )
        validation = _relation_aware_validation(
            plan,
            source_id="office_chair",
            target_id="desk",
            dense_classification={
                "classification": "valid_under",
                "deep_penetration_point_count": 0,
                "penetration_tolerance_m": 0.0125,
            },
        )
        self.assertTrue(validation["ok"], validation)
        self.assertEqual(len(validation["waived_broad_phase_violations"]), 1)
        self.assertEqual(
            validation["waived_broad_phase_violations"][0]["type"],
            "floor_collision",
        )
        cabinet = next(
            obj for obj in plan["objects"] if obj["id"] == "cabinet"
        )
        cabinet.update({"x": chair["x"], "y": chair["y"]})
        with_unrelated_collision = _relation_aware_validation(
            plan,
            source_id="office_chair",
            target_id="desk",
            dense_classification={
                "classification": "valid_under",
                "deep_penetration_point_count": 0,
                "penetration_tolerance_m": 0.0125,
            },
        )
        self.assertFalse(with_unrelated_collision["ok"])
        self.assertTrue(
            any(
                violation["type"] == "floor_collision"
                and "cabinet" in violation["objects"]
                for violation in with_unrelated_collision["violations"]
            )
        )

    def test_relation_sdf_repair_is_opt_in(self) -> None:
        args = build_parser().parse_args(
            ["--prompt", "study", "--output-dir", "/tmp/reference-sdf"]
        )
        self.assertFalse(args.relation_sdf_repair)


if __name__ == "__main__":
    unittest.main()
