from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.exact_predicates import (
    get_exact_predicate_backend,
)
from sage.experiments.codex_trellis_scene_v2.mesh_verifier import (
    intersection_tolerance,
    prepare_triangle_mesh,
    prepare_triangle_mesh_cached,
    triangles_intersect_exact,
    verify_mesh_intersection,
)


class MeshVerifierTest(unittest.TestCase):
    def test_separated_boxes_have_no_surface_intersection(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        result = verify_mesh_intersection(first, second, second_transform={"x": 2.0})
        self.assertTrue(result["complete"])
        self.assertFalse(result["intersects"])
        self.assertFalse(result["exact_predicates"])
        self.assertEqual(
            result["verification_class"], "conservative_broad_phase_verified"
        )

    def test_unavailable_backend_is_explicit_floating_point_verification(self) -> None:
        first = trimesh.creation.box(extents=(1, 1, 1))
        second = trimesh.creation.box(extents=(1, 1, 1))
        result = verify_mesh_intersection(
            first, second, second_transform={"x": 2.0}, exact_backend=False
        )
        self.assertFalse(result["exact_predicates"])
        self.assertEqual(result["verification_class"], "floating_point_verified")

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
        result = verify_mesh_intersection(first, second, second_transform={"z": 1.0})
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

    def test_static_target_bvh_is_reused_across_calls(self) -> None:
        mesh = trimesh.creation.box(extents=(1, 1, 1))
        with TemporaryDirectory() as directory:
            first = prepare_triangle_mesh_cached(
                mesh,
                transform={"x": 2.0},
                tolerance=1e-9,
                cache_directory=Path(directory),
            )
            second = prepare_triangle_mesh_cached(
                mesh,
                transform={"x": 2.0},
                tolerance=1e-9,
                cache_directory=Path(directory),
            )
        self.assertFalse(first.persistent_cache_hit)
        self.assertTrue(second.persistent_cache_hit)
        self.assertEqual(first.cache_key, second.cache_key)
        np.testing.assert_array_equal(first.soup.triangles, second.soup.triangles)

    def test_native_exact_triangle_predicates_cover_coplanar_and_crossing(self) -> None:
        backend = get_exact_predicate_backend(force_reload=True)
        self.assertIsNotNone(backend)
        base = np.asarray([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float64)
        coplanar = np.asarray(
            [[0.2, 0.2, 0], [0.8, 0.2, 0], [0.2, 0.8, 0]], dtype=np.float64
        )
        crossing = np.asarray(
            [[0.2, 0.2, -1], [0.2, 0.2, 1], [0.8, 0.2, 0]], dtype=np.float64
        )
        separate = coplanar + np.asarray([2.0, 0.0, 0.0])
        self.assertTrue(triangles_intersect_exact(base, coplanar, backend=backend))
        self.assertTrue(triangles_intersect_exact(base, crossing, backend=backend))
        self.assertFalse(triangles_intersect_exact(base, separate, backend=backend))


if __name__ == "__main__":
    unittest.main()
