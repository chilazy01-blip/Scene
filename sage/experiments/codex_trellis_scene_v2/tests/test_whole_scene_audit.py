from __future__ import annotations

from copy import deepcopy
import unittest

import numpy as np
import trimesh

from ..instance_groups import recover_orphan_matched_groups
from ..whole_scene_audit import (
    audit_glb_world_transforms,
    audit_plan,
    refresh_typed_scene_graph,
)


def _architecture() -> dict:
    return {
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
                "center": 3.3,
                "width": 1.0,
                "height": 1.0,
                "sill_height": 1.0,
            }
        ],
        "floor": {
            "id": "floor",
            "material": {"material_id": "wood", "texture_type": "procedural"},
        },
        "wall_finish": {
            "default": {"material_id": "plaster", "texture_type": "procedural"},
            "overrides": {},
        },
    }


def _plan() -> dict:
    plan = {
        "room_type": "bedroom",
        "room": {"width": 5.0, "length": 5.0, "height": 2.7},
        "architecture": _architecture(),
        "object_budget": {
            "hard_min": 0,
            "target_max": 20,
            "max_auto_inferred_objects": 20,
            "hard_runtime_limit": 40,
            "required_object_ids": ["wardrobe", "table", "lamp"],
        },
        "objects": [
            {
                "id": "wardrobe",
                "category": "wardrobe",
                "placement_type": "floor",
                "x": 0.3,
                "y": 1.0,
                "z": 0.0,
                "yaw": 90.0,
                "dimensions": {"width": 1.2, "length": 0.6, "height": 2.0},
                "preferred_wall": "west",
                "wall_constraint_strength": "hard",
                "asset_canonical_front": {"axis": "-y", "confidence": 0.9},
                "facing_constraint": {
                    "mode": "into_room",
                    "wall": "west",
                    "front_clearance_depth": 0.65,
                    "tolerance_degrees": 15.0,
                },
            },
            {
                "id": "table",
                "category": "table",
                "placement_type": "floor",
                "x": 3.0,
                "y": 3.0,
                "z": 0.0,
                "yaw": 0.0,
                "dimensions": {"width": 1.0, "length": 1.0, "height": 0.8},
            },
            {
                "id": "lamp",
                "category": "table_lamp",
                "placement_type": "support",
                "support_id": "table",
                "x": 3.0,
                "y": 3.0,
                "z": 0.8,
                "yaw": 0.0,
                "dimensions": {"width": 0.2, "length": 0.2, "height": 0.4},
            },
        ],
        "relations": [
            {
                "source": "lamp",
                "type": "supported_by",
                "target": "table",
                "strength": "hard",
            }
        ],
        "instance_groups": [],
        "constraint_scopes": [],
    }
    refresh_typed_scene_graph(plan)
    return plan


class WholeSceneAuditTest(unittest.TestCase):
    def test_verified_matching_pair_evidence_recovers_orphan_contract(self) -> None:
        plan = _plan()
        plan["description"] = "Place exactly two matching nightstands beside the bed."
        plan["objects"].extend(
            [
                {
                    "id": f"nightstand_{role}",
                    "category": "nightstand",
                    "placement_type": "floor",
                    "instance_group_id": "matching_nightstand_pair",
                    "instance_group_role": f"{role}_member",
                    "asset_id": "nightstand_oak_001",
                    "asset_source": "curated_library",
                    "instance_group_asset_family": "same_asset:nightstand_oak_001",
                    "x": x,
                    "y": 4.0,
                    "z": 0.0,
                    "yaw": 0.0,
                    "dimensions": {"width": 0.5, "length": 0.4, "height": 0.6},
                }
                for role, x in (("left", 1.0), ("right", 2.8))
            ]
        )
        recovered = recover_orphan_matched_groups(plan)
        self.assertEqual([item["group_id"] for item in recovered], ["matching_nightstand_pair"])
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertEqual(report["instance_groups"]["orphan_member_count"], 0)
        self.assertEqual(report["instance_groups"]["valid_count"], 1)

    def test_refresh_closes_graph_object_relation_and_pose_coverage(self) -> None:
        plan = _plan()
        plan["objects"].append(
            {
                "id": "late_object",
                "category": "stool",
                "placement_type": "floor",
                "x": 2.0,
                "y": 1.0,
                "z": 0.0,
                "yaw": 0.0,
                "dimensions": {"width": 0.4, "length": 0.4, "height": 0.4},
            }
        )
        stale = audit_plan(plan)
        self.assertFalse(stale["typed_scene_graph"]["ok"])
        self.assertEqual(stale["typed_scene_graph"]["missing_object_node_ids"], ["late_object"])

        refresh_typed_scene_graph(plan)
        repaired = audit_plan(plan)
        self.assertTrue(repaired["typed_scene_graph"]["ok"])
        self.assertEqual(repaired["typed_scene_graph"]["actual_object_node_count"], 4)

    def test_missing_support_is_a_whole_scene_failure(self) -> None:
        plan = _plan()
        next(item for item in plan["objects"] if item["id"] == "lamp")["support_id"] = "missing"
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertFalse(report["whole_scene_ok"])
        self.assertEqual(report["support_parent"]["failure_count"], 1)

    def test_wall_facing_regression_is_a_whole_scene_failure(self) -> None:
        plan = _plan()
        wardrobe = next(item for item in plan["objects"] if item["id"] == "wardrobe")
        wardrobe["yaw"] = 270.0
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertFalse(report["whole_scene_ok"])
        self.assertEqual(report["functional_facing"]["failure_count"], 1)

    def test_orphan_pair_members_are_a_whole_scene_failure(self) -> None:
        plan = _plan()
        plan["objects"].extend(
            [
                {
                    "id": f"slipper_{index}",
                    "category": "slipper",
                    "placement_type": "floor",
                    "instance_group_id": "missing_pair_contract",
                    "x": 2.0 + index * 0.3,
                    "y": 1.0,
                    "z": 0.0,
                    "yaw": 0.0,
                    "dimensions": {"width": 0.2, "length": 0.1, "height": 0.08},
                }
                for index in range(2)
            ]
        )
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertFalse(report["whole_scene_ok"])
        self.assertEqual(report["instance_groups"]["orphan_member_count"], 2)

    def test_window_obstruction_is_a_whole_scene_failure(self) -> None:
        plan = _plan()
        wardrobe = next(item for item in plan["objects"] if item["id"] == "wardrobe")
        wardrobe["y"] = 3.3
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertFalse(report["whole_scene_ok"])
        self.assertTrue(
            any(
                item["type"] == "window_obstruction"
                for item in report["architecture_openings_and_entry"]["failures"]
            )
        )

    def test_blocked_wardrobe_access_is_a_whole_scene_failure(self) -> None:
        plan = _plan()
        plan["objects"].append(
            {
                "id": "blocking_box",
                "category": "stool",
                "placement_type": "floor",
                "x": 0.95,
                "y": 1.0,
                "z": 0.0,
                "yaw": 0.0,
                "dimensions": {"width": 0.2, "length": 0.2, "height": 0.4},
            }
        )
        refresh_typed_scene_graph(plan)
        report = audit_plan(plan)
        self.assertFalse(report["whole_scene_ok"])
        self.assertEqual(report["operation_clearance"]["failure_count"], 1)
        self.assertEqual(
            report["operation_clearance"]["results"][0]["blocking_object_ids"],
            ["blocking_box"],
        )

    def test_glb_world_transform_mismatch_and_negative_determinant_fail(self) -> None:
        plan = {
            "architecture": {},
            "objects": [
                {
                    "id": "box",
                    "x": 1.0,
                    "y": 1.0,
                    "z": 0.0,
                    "yaw": 0.0,
                    "dimensions": {"width": 1.0, "length": 1.0, "height": 1.0},
                }
            ],
        }

        def scene_with_root(root_matrix: np.ndarray) -> trimesh.Scene:
            scene = trimesh.Scene()
            scene.add_geometry(
                trimesh.creation.box(extents=[1.0, 1.0, 1.0]),
                geom_name="box_geometry_0",
                node_name="box_geometry_0",
                parent_node_name="box_root",
                transform=np.eye(4),
            )
            scene.graph.update(
                frame_from="world", frame_to="box_root", matrix=root_matrix
            )
            return scene

        correct = np.eye(4)
        correct[:3, 3] = [1.0, 0.5, -1.0]
        self.assertTrue(audit_glb_world_transforms(plan, scene_with_root(correct))["ok"])

        shifted = correct.copy()
        shifted[0, 3] += 0.2
        self.assertFalse(audit_glb_world_transforms(plan, scene_with_root(shifted))["ok"])

        reflected = correct.copy()
        reflected[0, 0] = -1.0
        report = audit_glb_world_transforms(plan, scene_with_root(reflected))
        self.assertFalse(report["ok"])
        self.assertFalse(report["results"][0]["positive_determinant"])


if __name__ == "__main__":
    unittest.main()
