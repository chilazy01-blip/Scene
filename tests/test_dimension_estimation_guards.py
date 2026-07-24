from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "sage" / "scripts"
for path in (str(SCRIPTS_DIR), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_tree_sage_scene as scene  # noqa: E402


class DimensionEstimationGuardTests(unittest.TestCase):
    def test_normalize_preserves_valid_agent_dimensions(self) -> None:
        raw_graph = {
            "scene_id": "dimension_guard",
            "room": {"width": 5.2, "length": 4.2, "height": 2.7},
            "objects": [
                {
                    "id": "left_slipper",
                    "category": "slipper",
                    "description": "slipper on the rug near the foot of the bed",
                    "asset_prompt": "single navy slipper, object only",
                    "dimensions": {"width": 0.12, "length": 0.28, "height": 0.07},
                    "agent_semantics": {"semantic_class": "decor", "layout_role": "floor_decor"},
                },
                {
                    "id": "desk",
                    "category": "desk",
                    "description": "writing desk under the window",
                    "dimensions": {"width": 1.25, "length": 0.62, "height": 0.75},
                    "agent_semantics": {"semantic_class": "table_anchor", "layout_role": "floor_branch_anchor"},
                },
                {
                    "id": "floating_shelf",
                    "category": "wall shelf",
                    "description": "floating shelf mounted above the desk",
                    "dimensions": {"width": 0.9, "length": 0.18, "height": 0.05},
                    "agent_semantics": {"semantic_class": "wall_attached", "layout_role": "wall_branch"},
                },
            ],
            "relations": [],
        }

        normalized = scene.normalize_scene_graph(raw_graph, "test", max_objects=10)
        dimensions = {obj["id"]: obj["dimensions"] for obj in normalized["objects"]}

        self.assertEqual(dimensions["left_slipper"], {"width": 0.12, "length": 0.28, "height": 0.07})
        self.assertEqual(dimensions["desk"], {"width": 1.25, "length": 0.62, "height": 0.75})
        self.assertEqual(dimensions["floating_shelf"], {"width": 0.9, "length": 0.18, "height": 0.05})

    def test_relational_context_does_not_change_physical_kind(self) -> None:
        slipper = {
            "id": "left_slipper",
            "category": "slipper",
            "description": "slipper on the rug near the bed and below the window",
            "agent_semantics": {"semantic_class": "decor", "layout_role": "floor_decor"},
        }
        rug = {
            "id": "area_rug",
            "category": "rug",
            "description": "rug under the bed",
            "agent_semantics": {"semantic_class": "floor_covering", "layout_role": "floor_decor"},
        }

        self.assertTrue(scene._is_footwear_object(slipper))
        self.assertFalse(scene._is_floor_covering(slipper))
        self.assertEqual(scene._scale_kind(slipper), "footwear")
        self.assertTrue(scene._is_floor_covering(rug))
        self.assertEqual(scene._scale_kind(rug), "floor_covering")

    def test_identity_only_defaults_ignore_context_objects(self) -> None:
        slipper = {
            "id": "left_slipper",
            "category": "slipper",
            "description": "slipper on rug near bed",
        }
        desk = {
            "id": "desk",
            "category": "desk",
            "description": "desk under window",
            "dimensions": {"width": 1.25, "length": 0.62, "height": 0.75},
        }
        shelf = {
            "id": "floating_shelf",
            "category": "wall shelf",
            "description": "shelf above desk",
            "dimensions": {"width": 0.9, "length": 0.18, "height": 0.05},
        }

        self.assertEqual(scene._default_dimensions(slipper), {"width": 0.14, "length": 0.3, "height": 0.08})
        self.assertEqual(scene._default_dimensions(desk), {"width": 1.25, "length": 0.62, "height": 0.75})
        self.assertEqual(scene._default_dimensions(shelf), {"width": 0.9, "length": 0.18, "height": 0.05})

    def test_footwear_bounds_are_category_specific(self) -> None:
        bounds = scene._scale_prior_bounds_for_object(
            {"id": "right_slipper", "category": "slipper"},
            {"width": 5.2, "length": 4.2, "height": 2.7},
        )
        self.assertEqual(bounds["width"], (0.06, 0.28))
        self.assertEqual(bounds["length"], (0.12, 0.45))
        self.assertEqual(bounds["height"], (0.015, 0.2))

    def test_excessive_reference_scale_change_is_rejected(self) -> None:
        plan = {
            "room": {"width": 5.2, "length": 4.2, "height": 2.7},
            "objects": [
                {
                    "id": "desk",
                    "category": "desk",
                    "dimensions": {"width": 1.25, "length": 0.62, "height": 0.75},
                    "placement_type": "floor",
                }
            ],
        }
        priors = {
            "desk": {
                "dimensions": {"width": 3.0, "length": 2.0, "height": 1.5},
                "source": "reference_scale_estimator",
                "source_path": "reference_scale_estimator",
            }
        }

        report = scene.apply_object_scale_priors(plan, priors, enabled=True, stage="test")

        self.assertEqual(plan["objects"][0]["dimensions"], {"width": 1.25, "length": 0.62, "height": 0.75})
        self.assertEqual(report["applied_count"], 0)
        self.assertEqual(report["skipped"][0]["reason"], "excessive_reference_scale_change")
        self.assertGreater(report["skipped"][0]["max_axis_ratio"], 2.0)

    def test_wall_affinity_resolves_contact_separately_from_image_edge_proximity(self) -> None:
        raw_graph = {
            "scene_id": "corner_desk_wall_affinity",
            "room": {"width": 5.2, "length": 4.4, "height": 2.6},
            "objects": [
                {
                    "id": "desk",
                    "category": "desk",
                    "description": "writing desk in the back-left corner under a floating shelf",
                    "image_bbox": [0.047, 0.475, 0.286, 0.724],
                    "dimensions": {"width": 1.25, "length": 0.62, "height": 0.74},
                    "agent_semantics": {
                        "semantic_class": "table_anchor",
                        "layout_role": "floor_branch_anchor",
                        "wall_relation": {"mode": "against", "wall_id": "wall_west", "confidence": 0.76},
                        "pose_constraints": {
                            "expected_pose": "wall_flush",
                            "wall_id": "wall_west",
                            "confidence": 0.70,
                        },
                    },
                },
                {
                    "id": "floating_shelf",
                    "category": "wall shelf",
                    "dimensions": {"width": 0.95, "length": 0.22, "height": 0.05},
                    "agent_semantics": {
                        "semantic_class": "wall_attached",
                        "layout_role": "wall_branch",
                        "wall_relation": {"mode": "attached", "wall_id": "wall_north", "confidence": 0.74},
                    },
                },
                {
                    "id": "chair",
                    "category": "office chair",
                    "dimensions": {"width": 0.62, "length": 0.62, "height": 1.0},
                    "agent_semantics": {
                        "semantic_class": "seating",
                        "layout_role": "seating_child",
                        "wall_relation": {"mode": "near", "wall_id": "wall_west", "confidence": 0.66},
                    },
                },
            ],
            "relations": [
                {"type": "against_wall", "subject": "desk", "object": "wall_west", "confidence": 0.76},
                {"type": "against_wall", "subject": "desk", "object": "wall_north", "confidence": 0.82},
                {"type": "attached_to", "subject": "floating_shelf", "object": "wall_north", "confidence": 0.74},
                {"type": "above", "subject": "floating_shelf", "object": "desk", "confidence": 0.93},
                {"type": "near", "subject": "chair", "object": "wall_west", "confidence": 0.66},
                {"type": "facing", "subject": "chair", "object": "desk", "confidence": 0.80},
            ],
        }
        graph = scene.normalize_scene_graph(raw_graph, "test", max_objects=10)
        graph["_reference_spatial_order_groups"] = [
            {
                "group_id": "desk_branch",
                "scope": "local_branch",
                "objects": ["desk", "chair"],
                "left_to_right": ["desk", "chair"],
                "front_to_back": ["chair", "desk"],
            }
        ]

        candidate_report = scene.resolve_wall_affinity_candidates(graph)
        desk = next(obj for obj in graph["objects"] if obj["id"] == "desk")
        affinity = desk["agent_semantics"]["wall_affinity"]
        self.assertEqual(affinity["contact_wall"], "wall_north")
        self.assertIn("wall_west", affinity["near_walls"])
        self.assertGreaterEqual(candidate_report["resolved_count"], 2)

        refiner_report = scene.apply_reference_consistency_refiner(
            graph,
            {"branch_relation_mode_enabled": True},
            enabled=True,
        )
        scene.normalize_wall_pose_constraints(graph)
        self.assertEqual(desk["agent_semantics"]["wall_relation"]["wall_id"], "wall_north")
        self.assertTrue(
            any(
                warning.get("type") == "side_wall_cluster_rejected_by_contact_wall"
                for warning in refiner_report.get("warnings", [])
                if isinstance(warning, dict)
            )
        )

    def test_only_wall_slabs_receive_thin_axis_clamp(self) -> None:
        desk = {
            "id": "desk",
            "category": "desk",
            "dimensions": {"width": 1.25, "length": 0.62, "height": 0.74},
            "agent_semantics": {"semantic_class": "table_anchor", "layout_role": "floor_branch_anchor"},
        }
        shelf = {
            "id": "floating_shelf",
            "category": "wall shelf",
            "description": "floating shelf mounted above the desk",
            "asset_prompt": "single wall-mounted shelf for books and small tabletop decor",
            "dimensions": {"width": 0.95, "length": 0.22, "height": 0.05},
            "agent_semantics": {"semantic_class": "wall_attached", "layout_role": "wall_branch"},
        }
        art = {
            "id": "wall_art",
            "category": "framed wall art",
            "dimensions": {"width": 0.82, "length": 0.20, "height": 0.50},
            "agent_semantics": {"semantic_class": "wall_attached", "layout_role": "wall_branch"},
        }

        self.assertEqual(scene._wall_attachment_class(desk), "floor_against_wall")
        self.assertEqual(scene._wall_attachment_class(shelf), "wall_fixture_volume")
        self.assertEqual(scene._wall_attachment_class(art), "wall_slab")
        self.assertFalse(scene._clamp_wall_slab_thickness(desk, 0.08))
        self.assertFalse(scene._clamp_wall_slab_thickness(shelf, 0.08))
        self.assertTrue(scene._clamp_wall_slab_thickness(art, 0.08))
        self.assertEqual(desk["dimensions"]["length"], 0.62)
        self.assertEqual(shelf["dimensions"]["length"], 0.22)
        self.assertEqual(art["dimensions"]["length"], 0.08)

    def test_wall_parent_cannot_flatten_grounded_support_furniture(self) -> None:
        raw_graph = {
            "scene_id": "wall_parent_dimension_guard",
            "room": {"width": 5.2, "length": 4.4, "height": 2.6},
            "objects": [
                {
                    "id": "desk",
                    "category": "desk",
                    "image_bbox": [0.10, 0.40, 0.32, 0.72],
                    "dimensions": {"width": 1.25, "length": 0.62, "height": 0.74},
                    "agent_semantics": {
                        "semantic_class": "table_anchor",
                        "layout_role": "floor_branch_anchor",
                        "wall_relation": {"mode": "attached", "wall_id": "wall_north", "confidence": 0.9},
                        "pose_constraints": {"expected_pose": "wall_flush", "wall_id": "wall_north", "confidence": 0.9},
                    },
                },
                {
                    "id": "desk_lamp",
                    "category": "desk lamp",
                    "dimensions": {"width": 0.22, "length": 0.22, "height": 0.55},
                    "agent_semantics": {"semantic_class": "lighting", "layout_role": "tabletop_child"},
                },
            ],
            "relations": [
                {"type": "attached_to", "subject": "desk", "object": "wall_north", "confidence": 0.9},
                {"type": "on", "subject": "desk_lamp", "object": "desk", "confidence": 0.95},
            ],
        }
        graph = scene.normalize_scene_graph(raw_graph, "test", max_objects=10)
        support_tree, cross_constraints, parent, relation_to_parent = scene.build_support_tree(graph)
        plan = scene.build_plan_from_scene_graph(graph, support_tree, cross_constraints, parent, relation_to_parent)
        objects = {obj["id"]: obj for obj in plan["objects"]}

        self.assertEqual(objects["desk"]["placement_type"], "floor")
        self.assertEqual(objects["desk"]["dimensions"], {"width": 1.25, "length": 0.62, "height": 0.74})
        registry = scene.build_support_surface_registry(plan, None)
        self.assertIn("desk", registry["surfaces_by_owner"])
        self.assertIn("desk_top", registry["surfaces_by_owner"]["desk"])


if __name__ == "__main__":
    unittest.main()
