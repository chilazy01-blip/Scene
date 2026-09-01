from __future__ import annotations

import unittest

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.collision_mesh_cleanup import (
    CollisionMeshCleanupConfig,
    cleanup_collision_mesh,
)
from sage.experiments.codex_trellis_scene_v2.multilevel_proxy import (
    build_component_aware_sdf,
)
from sage.experiments.codex_trellis_scene_v2.tests.test_multilevel_proxy import (
    open_shelf_mesh,
)


class CollisionMeshCleanupTest(unittest.TestCase):
    def test_welds_triangle_soup_without_changing_bounds(self) -> None:
        box = trimesh.creation.box(extents=(1.0, 0.5, 0.4))
        triangles = np.asarray(box.triangles)
        soup = trimesh.Trimesh(
            vertices=triangles.reshape((-1, 3)),
            faces=np.arange(len(triangles) * 3).reshape((-1, 3)),
            process=False,
        )
        cleaned, report = cleanup_collision_mesh(soup)
        self.assertTrue(report["accepted"])
        self.assertGreater(report["cleanup"]["welded_vertex_count"], 0)
        self.assertEqual(report["cleanup"]["kept_component_count"], 1)
        np.testing.assert_allclose(cleaned.bounds, box.bounds)

    def test_removes_tiny_floating_triangle_but_preserves_open_shelf(self) -> None:
        shelf = open_shelf_mesh()
        fragment = trimesh.Trimesh(
            vertices=[[2.0, 2.0, 2.0], [2.0001, 2.0, 2.0], [2.0, 2.0001, 2.0]],
            faces=[[0, 1, 2]],
            process=False,
        )
        noisy = trimesh.util.concatenate((shelf, fragment))
        cleaned, report = cleanup_collision_mesh(
            noisy,
            CollisionMeshCleanupConfig(maximum_bounds_change_m=3.0),
        )
        self.assertTrue(report["accepted"])
        self.assertGreaterEqual(report["cleanup"]["removed_component_count"], 1)
        proxy = build_component_aware_sdf(
            cleaned,
            pitch=0.025,
            padding_voxels=3,
            surface_dilation_voxels=1,
        )
        distances = proxy.query(np.asarray([[0.0, 0.0, 0.5], [0.0, -0.24, 0.5]]))
        self.assertGreater(distances[0], 0.05)
        self.assertGreater(distances[1], 0.0)

    def test_rejects_aggressive_component_cap(self) -> None:
        parts = []
        for x in (-1.0, 0.0, 1.0):
            part = trimesh.creation.box(extents=(0.4, 0.4, 0.4))
            part.apply_translation((x, 0.0, 0.0))
            parts.append(part)
        _, report = cleanup_collision_mesh(
            trimesh.util.concatenate(parts),
            CollisionMeshCleanupConfig(
                maximum_components=1,
                minimum_retained_area_fraction=0.9,
                maximum_bounds_change_m=0.01,
            ),
        )
        self.assertFalse(report["accepted"])
        self.assertIn("retained_area_below_threshold", report["reasons"])


if __name__ == "__main__":
    unittest.main()
