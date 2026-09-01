from __future__ import annotations

import unittest

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.relation_geometry_bridge import (
    RELATION_GEOMETRY_BINDING_SCHEMA,
    RuntimeGeometryAsset,
    evaluate_geometry_bindings,
    reconcile_layout_validation_with_geometry_audit,
    validate_geometry_binding,
)
from sage.experiments.codex_trellis_scene_v2.tests.test_relation_geometry import (
    BoxProxy,
    MultiBoxProxy,
    box_surface_points,
)


class GenericBridgeTest(unittest.TestCase):
    def test_multiple_relation_types_share_one_opt_in_bridge(self) -> None:
        desk_mesh = trimesh.creation.box(extents=(2.0, 1.0, 0.1))
        desk_mesh.apply_translation((0, 0, -0.05))
        cup_mesh = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
        cup_mesh.apply_translation((0, 0, 0.05))
        shelf_boxes = [
            BoxProxy((-0.5, -0.22, -0.05), (0.5, 0.22, 0.0)),
            BoxProxy((-0.5, -0.22, 0.5), (0.5, 0.22, 0.55)),
            BoxProxy((-0.5, 0.2, 0.0), (0.5, 0.22, 0.5)),
        ]
        shelf_mesh = trimesh.util.concatenate(
            [
                trimesh.creation.box(
                    extents=tuple(box.maximum - box.minimum),
                    transform=trimesh.transformations.translation_matrix(
                        tuple((box.maximum + box.minimum) / 2.0)
                    ),
                )
                for box in shelf_boxes
            ]
        )
        book_bounds = ((-0.1, -0.1, 0.05), (0.1, 0.1, 0.3))
        book_mesh = trimesh.creation.box(extents=(0.2, 0.2, 0.25))
        book_mesh.apply_translation((0, 0, 0.175))
        runtime = {
            "desk_asset": RuntimeGeometryAsset(
                capability={
                    "asset_id": "desk_asset",
                    "category": "desk",
                    "support_surfaces": [
                        {
                            "id": "top",
                            "center_m": [0, 0, 0],
                            "normal": [0, 0, 1],
                            "u_axis": [1, 0, 0],
                            "v_axis": [0, 1, 0],
                            "half_extents_m": [1, 0.5],
                            "contact_tolerance_m": 0.002,
                        }
                    ],
                },
                surface_points_local=box_surface_points((-1, -0.5, -0.1), (1, 0.5, 0)),
                proxy=BoxProxy((-1, -0.5, -0.1), (1, 0.5, 0)),
                proxy_hash="desk",
                mesh=desk_mesh,
            ),
            "cup_asset": RuntimeGeometryAsset(
                capability={"asset_id": "cup_asset", "category": "cup"},
                surface_points_local=box_surface_points((-0.05, -0.05, 0), (0.05, 0.05, 0.1)),
                proxy=BoxProxy((-0.05, -0.05, 0), (0.05, 0.05, 0.1)),
                proxy_hash="cup",
                mesh=cup_mesh,
            ),
            "shelf_asset": RuntimeGeometryAsset(
                capability={
                    "asset_id": "shelf_asset",
                    "category": "shelf",
                    "containment_volumes": [
                        {"id": "bay", "min_m": [-0.4, -0.2, 0], "max_m": [0.4, 0.2, 0.5]}
                    ],
                },
                surface_points_local=np.concatenate(
                    [box_surface_points(tuple(box.minimum), tuple(box.maximum), 3) for box in shelf_boxes]
                ),
                proxy=MultiBoxProxy(shelf_boxes),
                proxy_hash="shelf",
                mesh=shelf_mesh,
            ),
            "book_asset": RuntimeGeometryAsset(
                capability={"asset_id": "book_asset", "category": "book"},
                surface_points_local=box_surface_points(*book_bounds),
                proxy=BoxProxy(*book_bounds),
                proxy_hash="book",
                mesh=book_mesh,
            ),
        }
        plan = {
            "objects": [
                {"id": "desk", "asset_id": "desk_asset", "x": 0, "y": 0, "z": 0, "yaw": 0},
                {"id": "cup", "asset_id": "cup_asset", "x": 0, "y": 0, "z": 0, "yaw": 0},
                {"id": "shelf", "asset_id": "shelf_asset", "x": 3, "y": 0, "z": 0, "yaw": 0},
                {"id": "book", "asset_id": "book_asset", "x": 3, "y": 0, "z": 0, "yaw": 0},
            ],
            "relations": [
                {"source": "cup", "type": "supported_by", "target": "desk", "strength": "hard"},
                {"source": "book", "type": "contained_in", "target": "shelf", "strength": "hard"},
            ],
        }
        binding = {
            "schema": RELATION_GEOMETRY_BINDING_SCHEMA,
            "relations": [
                {
                    "source_object_id": "cup",
                    "relation_type": "supported_by",
                    "target_object_id": "desk",
                    "target_slot_id": "top",
                    "triangle_verification": "off",
                },
                {
                    "source_object_id": "book",
                    "relation_type": "contained_in",
                    "target_object_id": "shelf",
                    "target_slot_id": "bay",
                    "triangle_verification": "always",
                },
            ],
        }
        audit = evaluate_geometry_bindings(plan, binding, runtime)
        self.assertTrue(audit["ok"])
        self.assertEqual(audit["relation_count"], 2)
        self.assertIsNotNone(audit["relations"][1]["triangle_verification"])

    def test_binding_rejects_unknown_relation(self) -> None:
        validation = validate_geometry_binding(
            {
                "schema": RELATION_GEOMETRY_BINDING_SCHEMA,
                "relations": [
                    {
                        "source_object_id": "a",
                        "relation_type": "category_specific_magic",
                        "target_object_id": "b",
                        "target_slot_id": "slot",
                    }
                ],
            }
        )
        self.assertFalse(validation["ok"])

    def test_geometry_audit_waives_only_the_certified_aabb_pair(self) -> None:
        validation = {
            "schema": "codex_trellis_layout_validation_v2",
            "ok": False,
            "hard_violation_count": 2,
            "soft_violation_count": 0,
            "violations": [
                {
                    "type": "floor_collision",
                    "severity": "hard",
                    "objects": ["desk", "chair"],
                },
                {"type": "door_clearance", "severity": "hard", "object_id": "bed"},
            ],
        }
        audit = {
            "schema": "codex_trellis_relation_geometry_audit_v1",
            "relations": [
                {
                    "source_object_id": "chair",
                    "relation_type": "tucked_under",
                    "target_object_id": "desk",
                    "accepted": True,
                    "triangle_verification": {"complete": True, "intersects": False},
                    "certificate": {
                        "certificate_hash": "verified",
                        "collision": {
                            "complete": True,
                            "source_to_target": {"deep_count": 0},
                            "target_to_source": {"deep_count": 0},
                        },
                    },
                }
            ],
        }

        reconciled = reconcile_layout_validation_with_geometry_audit(validation, audit)

        self.assertFalse(reconciled["ok"])
        self.assertEqual(reconciled["hard_violation_count"], 1)
        self.assertEqual(reconciled["geometry_waived_violation_count"], 1)
        self.assertEqual(reconciled["violations"][0]["type"], "door_clearance")

    def test_intersecting_triangle_report_cannot_waive_aabb_collision(self) -> None:
        validation = {
            "schema": "codex_trellis_layout_validation_v2",
            "ok": False,
            "hard_violation_count": 1,
            "soft_violation_count": 0,
            "violations": [
                {
                    "type": "floor_collision",
                    "severity": "hard",
                    "objects": ["desk", "chair"],
                }
            ],
        }
        audit = {
            "schema": "codex_trellis_relation_geometry_audit_v1",
            "relations": [
                {
                    "source_object_id": "chair",
                    "relation_type": "tucked_under",
                    "target_object_id": "desk",
                    "accepted": True,
                    "triangle_verification": {"complete": True, "intersects": True},
                    "certificate": {
                        "collision": {
                            "complete": True,
                            "source_to_target": {"deep_count": 0},
                            "target_to_source": {"deep_count": 0},
                        }
                    },
                }
            ],
        }

        reconciled = reconcile_layout_validation_with_geometry_audit(validation, audit)

        self.assertFalse(reconciled["ok"])
        self.assertEqual(reconciled["hard_violation_count"], 1)
        self.assertEqual(reconciled["geometry_waived_violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
