from __future__ import annotations

import unittest

import trimesh

from sage.experiments.codex_trellis_scene_v2.mesh_verifier import (
    intersection_tolerance,
    prepare_triangle_mesh,
    verify_mesh_intersection,
)


class MeshVerifierTest(unittest.TestCase):
    def test_separated_boxes_have_no_surface_intersection(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        result = verify_mesh_intersection(
            first, second, second_transform={"x": 2.0}
        )
        self.assertTrue(result["complete"])
        self.assertFalse(result["intersects"])
        self.assertFalse(result["exact_predicates"])

    def test_overlapping_boxes_have_surface_intersections(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        result = verify_mesh_intersection(
            first, second, second_transform={"x": 0.4, "y": 0.1}
        )
        self.assertTrue(result["complete"])
        self.assertTrue(result["intersects"])
        self.assertGreater(result["intersection_pair_count"], 0)

    def test_coplanar_touch_is_reported_for_relation_level_classification(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        result = verify_mesh_intersection(
            first, second, second_transform={"z": 1.0}
        )
        self.assertTrue(result["intersects"])

    def test_candidate_budget_produces_inconclusive_not_false_clearance(self) -> None:
        first = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        second = trimesh.creation.icosphere(subdivisions=2, radius=1.0)
        result = verify_mesh_intersection(
            first, second, second_transform={"x": 0.2}, maximum_candidate_pairs=1
        )
        self.assertFalse(result["complete"])

    def test_prepared_second_mesh_reuses_static_bvh(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        tolerance = intersection_tolerance(first, second)
        prepared = prepare_triangle_mesh(
            second,
            transform={"x": 2.0},
            tolerance=tolerance,
        )
        result = verify_mesh_intersection(
            first,
            second,
            second_transform={"x": 2.0},
            prepared_second=prepared,
        )
        self.assertTrue(result["complete"])
        self.assertFalse(result["intersects"])
        self.assertTrue(result["second_bvh_cache_used"])


if __name__ == "__main__":
    unittest.main()
