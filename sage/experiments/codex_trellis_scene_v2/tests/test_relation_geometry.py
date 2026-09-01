from __future__ import annotations

import unittest

import numpy as np

from sage.experiments.codex_trellis_scene_v2.relation_geometry import (
    certificate_is_fresh,
    compile_relation_geometry,
    evaluate_relation_geometry,
)


class BoxProxy:
    def __init__(self, minimum: tuple[float, float, float], maximum: tuple[float, float, float]):
        self.minimum = np.asarray(minimum, dtype=np.float64)
        self.maximum = np.asarray(maximum, dtype=np.float64)
        self.pitch = 0.001

    def query(self, points: np.ndarray) -> np.ndarray:
        points = np.asarray(points, dtype=np.float64)
        center = (self.minimum + self.maximum) / 2.0
        half = (self.maximum - self.minimum) / 2.0
        q = np.abs(points - center) - half
        outside = np.linalg.norm(np.maximum(q, 0.0), axis=1)
        inside = np.minimum(np.max(q, axis=1), 0.0)
        return outside + inside


class MultiBoxProxy:
    def __init__(self, boxes: list[BoxProxy]):
        self.boxes = boxes
        self.pitch = boxes[0].pitch

    def query(self, points: np.ndarray) -> np.ndarray:
        return np.min(np.stack([box.query(points) for box in self.boxes]), axis=0)


def box_surface_points(
    minimum: tuple[float, float, float],
    maximum: tuple[float, float, float],
    steps: int = 5,
) -> np.ndarray:
    minimum_array = np.asarray(minimum, dtype=np.float64)
    maximum_array = np.asarray(maximum, dtype=np.float64)
    axes = [
        np.linspace(minimum_array[index], maximum_array[index], steps)
        for index in range(3)
    ]
    points: list[list[float]] = []
    for x in axes[0]:
        for y in axes[1]:
            for z in axes[2]:
                if (
                    x in (axes[0][0], axes[0][-1])
                    or y in (axes[1][0], axes[1][-1])
                    or z in (axes[2][0], axes[2][-1])
                ):
                    points.append([x, y, z])
    return np.asarray(points, dtype=np.float64)


def capability(
    asset_id: str,
    category: str,
    **slots: object,
) -> dict[str, object]:
    return {"asset_id": asset_id, "category": category, **slots}


class RelationCompilationTest(unittest.TestCase):
    def test_same_containment_evaluator_handles_unseen_category(self) -> None:
        target = capability(
            "cabinet",
            "storage",
            containment_volumes=[
                {"id": "bay", "shape": "box", "min_m": [-1, -1, 0], "max_m": [1, 1, 2]}
            ],
        )
        first = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"},
            capability("book", "book"),
            target,
        )
        unseen = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"},
            capability("sample", "previously_unseen_category"),
            target,
        )
        self.assertEqual(first["evaluator"], "full_containment")
        self.assertEqual(first["evaluator"], unseen["evaluator"])

    def test_category_can_filter_authoring_but_does_not_choose_evaluator(self) -> None:
        target = capability(
            "cabinet",
            "storage",
            containment_volumes=[
                {
                    "id": "bay",
                    "shape": "box",
                    "min_m": [-1, -1, 0],
                    "max_m": [1, 1, 2],
                    "allowed_categories": ["book"],
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "not allowed"):
            compile_relation_geometry(
                {"type": "contained_in", "target_slot_id": "bay"},
                capability("cup", "cup"),
                target,
            )


class RelationEvaluationTest(unittest.TestCase):
    def test_cup_supported_by_desk(self) -> None:
        source = capability("cup", "cup")
        target = capability(
            "desk",
            "desk",
            support_surfaces=[
                {
                    "id": "top",
                    "center_m": [0, 0, 0],
                    "normal": [0, 0, 1],
                    "u_axis": [1, 0, 0],
                    "v_axis": [0, 1, 0],
                    "half_extents_m": [1, 0.5],
                    "contact_tolerance_m": 0.002,
                    "minimum_footprint_overlap": 0.5,
                }
            ],
        )
        contract = compile_relation_geometry(
            {"type": "supported_by", "target_slot_id": "top"}, source, target
        )
        cup_points = box_surface_points((-0.05, -0.05, 0), (0.05, 0.05, 0.1))
        desk_points = box_surface_points((-1, -0.5, -0.1), (1, 0.5, 0))
        result = evaluate_relation_geometry(
            contract,
            source_points_local=cup_points,
            target_points_local=desk_points,
            source_proxy=BoxProxy((-0.05, -0.05, 0), (0.05, 0.05, 0.1)),
            target_proxy=BoxProxy((-1, -0.5, -0.1), (1, 0.5, 0)),
        )
        self.assertTrue(result.accepted)
        hovering = evaluate_relation_geometry(
            contract,
            source_points_local=cup_points,
            target_points_local=desk_points,
            source_pose={"z": 0.03},
            source_proxy=BoxProxy((-0.05, -0.05, 0), (0.05, 0.05, 0.1)),
            target_proxy=BoxProxy((-1, -0.5, -0.1), (1, 0.5, 0)),
        )
        self.assertFalse(hovering.accepted)

    def test_open_shelf_containment_does_not_seal_opening(self) -> None:
        source = capability("book", "book")
        target = capability(
            "open_shelf",
            "shelf",
            containment_volumes=[
                {"id": "bay", "min_m": [-0.4, -0.2, 0], "max_m": [0.4, 0.2, 0.5]}
            ],
        )
        contract = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"}, source, target
        )
        book_bounds = ((-0.1, -0.12, 0.02), (0.1, 0.12, 0.32))
        book_points = box_surface_points(*book_bounds)
        frame_boxes = [
            BoxProxy((-0.45, -0.22, -0.05), (0.45, 0.22, 0.0)),
            BoxProxy((-0.45, -0.22, 0.5), (0.45, 0.22, 0.55)),
            BoxProxy((-0.45, -0.22, 0), (-0.4, 0.22, 0.5)),
            BoxProxy((0.4, -0.22, 0), (0.45, 0.22, 0.5)),
            BoxProxy((-0.4, 0.2, 0), (0.4, 0.22, 0.5)),
        ]
        frame_points = np.concatenate(
            [box_surface_points(tuple(box.minimum), tuple(box.maximum), 3) for box in frame_boxes]
        )
        result = evaluate_relation_geometry(
            contract,
            source_points_local=book_points,
            target_points_local=frame_points,
            source_proxy=BoxProxy(*book_bounds),
            target_proxy=MultiBoxProxy(frame_boxes),
        )
        self.assertTrue(result.accepted)

    def test_partial_entry_and_deep_collision_are_separate_predicates(self) -> None:
        source = capability("chair", "seat")
        target = capability(
            "desk",
            "table",
            free_space_volumes=[
                {
                    "id": "leg_bay",
                    "min_m": [-0.5, -0.35, 0],
                    "max_m": [0.5, 0.35, 0.7],
                    "minimum_geometry_fraction_inside": 0.2,
                }
            ],
        )
        contract = compile_relation_geometry(
            {"type": "tucked_under", "target_slot_id": "leg_bay"}, source, target
        )
        chair_bounds = ((-0.2, -0.2, 0), (0.2, 0.2, 0.5))
        chair_points = box_surface_points(*chair_bounds)
        desk_top = BoxProxy((-0.6, -0.4, 0.72), (0.6, 0.4, 0.78))
        desk_points = box_surface_points(tuple(desk_top.minimum), tuple(desk_top.maximum))
        accepted = evaluate_relation_geometry(
            contract,
            source_points_local=chair_points,
            target_points_local=desk_points,
            source_proxy=BoxProxy(*chair_bounds),
            target_proxy=desk_top,
        )
        self.assertTrue(accepted.accepted)
        colliding = evaluate_relation_geometry(
            contract,
            source_points_local=chair_points,
            target_points_local=desk_points,
            source_pose={"z": 0.5},
            source_proxy=BoxProxy(*chair_bounds),
            target_proxy=desk_top,
        )
        self.assertFalse(colliding.accepted)
        self.assertGreater(
            colliding.certificate["collision"]["source_to_target"]["deep_count"], 0
        )

    def test_partial_entry_can_use_functional_anchor_and_depth(self) -> None:
        source = capability(
            "chair",
            "seat",
            semantic_anchors=[
                {"id": "seat_front", "shape": "point", "point_m": [0, -0.25, 0.45]}
            ],
        )
        target = capability(
            "desk",
            "table",
            free_space_volumes=[
                {
                    "id": "bay",
                    "min_m": [-0.5, -0.36, 0],
                    "max_m": [0.5, 0.25, 0.63],
                    "entry_axis": [0, -1, 0],
                    "minimum_entry_depth_m": 0.05,
                    "minimum_geometry_fraction_inside": 1.0,
                }
            ],
        )
        contract = compile_relation_geometry(
            {
                "type": "tucked_under",
                "target_slot_id": "bay",
                "source_anchor_id": "seat_front",
            },
            source,
            target,
        )
        chair_bounds = ((-0.2, -0.3, 0), (0.2, 0.3, 0.6))
        chair_points = box_surface_points(*chair_bounds)
        desk_proxy = BoxProxy((-0.6, -0.4, 0.72), (0.6, 0.4, 0.78))
        desk_points = box_surface_points(tuple(desk_proxy.minimum), tuple(desk_proxy.maximum))
        accepted = evaluate_relation_geometry(
            contract,
            source_points_local=chair_points,
            target_points_local=desk_points,
            source_pose={"y": -0.54, "yaw_degrees": 180},
            source_proxy=BoxProxy(*chair_bounds),
            target_proxy=desk_proxy,
        )
        self.assertTrue(accepted.accepted)
        self.assertGreaterEqual(
            accepted.certificate["predicate"]["maximum_entry_depth_m"], 0.05
        )
        too_shallow = evaluate_relation_geometry(
            contract,
            source_points_local=chair_points,
            target_points_local=desk_points,
            source_pose={"y": -0.63, "yaw_degrees": 180},
            source_proxy=BoxProxy(*chair_bounds),
            target_proxy=desk_proxy,
        )
        self.assertFalse(too_shallow.accepted)

    def test_conservative_policy_rejects_missing_reverse_check(self) -> None:
        source = capability("book", "book")
        target = capability(
            "shelf",
            "shelf",
            containment_volumes=[
                {"id": "bay", "min_m": [-1, -1, 0], "max_m": [1, 1, 1]}
            ],
        )
        contract = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"}, source, target
        )
        result = evaluate_relation_geometry(
            contract,
            source_points_local=box_surface_points((-0.1, -0.1, 0.1), (0.1, 0.1, 0.3)),
            target_points_local=np.empty((0, 3)),
            target_proxy=BoxProxy((2, 2, 2), (3, 3, 3)),
        )
        self.assertFalse(result.accepted)
        self.assertFalse(result.certificate["collision"]["complete"])

    def test_certificate_becomes_stale_when_pose_changes(self) -> None:
        source = capability("book", "book")
        target = capability(
            "shelf",
            "shelf",
            containment_volumes=[
                {"id": "bay", "min_m": [-1, -1, 0], "max_m": [1, 1, 1]}
            ],
        )
        contract = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"}, source, target
        )
        points = box_surface_points((-0.1, -0.1, 0.1), (0.1, 0.1, 0.3))
        result = evaluate_relation_geometry(
            contract,
            source_points_local=points,
            target_points_local=box_surface_points((2, 2, 2), (3, 3, 3)),
            source_proxy=BoxProxy((-0.1, -0.1, 0.1), (0.1, 0.1, 0.3)),
            target_proxy=BoxProxy((2, 2, 2), (3, 3, 3)),
            proxy_hashes={"source": "a", "target": "b"},
        )
        self.assertTrue(
            certificate_is_fresh(
                result.certificate,
                contract=contract,
                source_pose=None,
                target_pose=None,
                proxy_hashes={"source": "a", "target": "b"},
            )
        )
        self.assertFalse(
            certificate_is_fresh(
                result.certificate,
                contract=contract,
                source_pose={"x": 0.01},
                target_pose=None,
                proxy_hashes={"source": "a", "target": "b"},
            )
        )


if __name__ == "__main__":
    unittest.main()
