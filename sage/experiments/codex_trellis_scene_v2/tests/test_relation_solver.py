from __future__ import annotations

import unittest

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.relation_geometry import (
    compile_relation_geometry,
)
from sage.experiments.codex_trellis_scene_v2.relation_solver import (
    optimize_relation_pose,
)
from sage.experiments.codex_trellis_scene_v2.tests.test_relation_geometry import (
    BoxProxy,
    box_surface_points,
    capability,
)


class GenericRelationSolverTest(unittest.TestCase):
    def test_containment_solver_uses_all_mesh_vertices_when_available(self) -> None:
        source = capability("unknown_asset", "unseen_category")
        target = capability(
            "open_storage",
            "storage",
            containment_volumes=[
                {"id": "bay", "min_m": [-0.5, -0.4, 0], "max_m": [0.5, 0.4, 0.6]}
            ],
        )
        contract = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"}, source, target
        )
        source_mesh = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
        source_mesh.apply_translation((0.0, 0.0, 0.1))
        # Samples omit an authored protruding vertex that must still invalidate
        # the preferred pose under complete convex-slot containment.
        vertices = np.vstack((source_mesh.vertices, [[0.61, 0.0, 0.1]]))
        source_mesh = trimesh.Trimesh(
            vertices=vertices, faces=source_mesh.faces, process=False
        )
        source_bounds = ((-0.1, -0.1, 0), (0.1, 0.1, 0.2))
        result = optimize_relation_pose(
            contract,
            source_points_local=box_surface_points(*source_bounds),
            target_points_local=box_surface_points((2, 2, 2), (3, 3, 3), 3),
            source_proxy=BoxProxy(*source_bounds),
            target_proxy=BoxProxy((2, 2, 2), (3, 3, 3)),
            preferred_target_local_pose={"x": 0, "y": 0, "z": 0, "yaw_degrees": 0},
            translation_step_m=0.2,
            source_mesh=source_mesh,
        )
        self.assertNotEqual(result["selected_target_local_pose"]["x"], 0.0)
        self.assertEqual(
            result["certificate"]["predicate"]["point_basis"],
            "all_mesh_vertices_convex_slot",
        )

    def test_unseen_object_is_moved_into_containment_volume(self) -> None:
        source = capability("unknown_asset", "unseen_category")
        target = capability(
            "open_storage",
            "storage",
            containment_volumes=[
                {"id": "bay", "min_m": [-0.5, -0.4, 0], "max_m": [0.5, 0.4, 0.6]}
            ],
        )
        contract = compile_relation_geometry(
            {"type": "contained_in", "target_slot_id": "bay"}, source, target
        )
        source_bounds = ((-0.1, -0.1, 0), (0.1, 0.1, 0.2))
        result = optimize_relation_pose(
            contract,
            source_points_local=box_surface_points(*source_bounds),
            target_points_local=box_surface_points((2, 2, 2), (3, 3, 3), 3),
            source_proxy=BoxProxy(*source_bounds),
            target_proxy=BoxProxy((2, 2, 2), (3, 3, 3)),
            preferred_target_local_pose={"x": 2, "y": 2, "z": 2, "yaw_degrees": 0},
            translation_step_m=0.2,
        )
        pose = result["selected_target_local_pose"]
        self.assertLessEqual(abs(pose["x"]), 0.4)
        self.assertLessEqual(abs(pose["y"]), 0.3)
        self.assertTrue(result["certificate"]["accepted"])

    def test_support_solver_aligns_bottom_with_surface(self) -> None:
        source = capability("cup", "cup")
        target = capability(
            "desk",
            "desk",
            support_surfaces=[
                {
                    "id": "top",
                    "center_m": [0, 0, 0.75],
                    "normal": [0, 0, 1],
                    "u_axis": [1, 0, 0],
                    "v_axis": [0, 1, 0],
                    "half_extents_m": [0.6, 0.3],
                    "contact_tolerance_m": 0.003,
                    "minimum_footprint_overlap": 0.5,
                }
            ],
        )
        contract = compile_relation_geometry(
            {"type": "supported_by", "target_slot_id": "top"}, source, target
        )
        cup_bounds = ((-0.05, -0.05, 0), (0.05, 0.05, 0.1))
        result = optimize_relation_pose(
            contract,
            source_points_local=box_surface_points(*cup_bounds),
            target_points_local=box_surface_points(
                (-0.7, -0.4, 0.65), (0.7, 0.4, 0.75)
            ),
            source_proxy=BoxProxy(*cup_bounds),
            target_proxy=BoxProxy((-0.7, -0.4, 0.65), (0.7, 0.4, 0.75)),
            preferred_target_local_pose={"x": 0.1, "y": 0.1, "z": 0, "yaw_degrees": 0},
            translation_step_m=0.2,
        )
        self.assertAlmostEqual(result["selected_target_local_pose"]["z"], 0.75)

    def test_contact_solver_places_source_against_vertical_plane(self) -> None:
        source = capability("crate", "unseen_category")
        target = capability(
            "panel",
            "panel",
            contact_surfaces=[
                {
                    "id": "front",
                    "center_m": [0, 0, 0.5],
                    "normal": [1, 0, 0],
                    "u_axis": [0, 1, 0],
                    "v_axis": [0, 0, 1],
                    "half_extents_m": [0.5, 0.5],
                    "contact_tolerance_m": 0.003,
                    "minimum_contact_fraction": 0.05,
                }
            ],
        )
        contract = compile_relation_geometry(
            {"type": "against", "target_slot_id": "front"}, source, target
        )
        crate_bounds = ((-0.1, -0.1, 0), (0.1, 0.1, 0.2))
        result = optimize_relation_pose(
            contract,
            source_points_local=box_surface_points(*crate_bounds),
            target_points_local=box_surface_points((-0.05, -0.5, 0), (0, 0.5, 1)),
            source_proxy=BoxProxy(*crate_bounds),
            target_proxy=BoxProxy((-0.05, -0.5, 0), (0, 0.5, 1)),
            preferred_target_local_pose={"x": 0.5, "y": 0, "z": 0.4, "yaw_degrees": 0},
            translation_step_m=0.2,
        )
        self.assertAlmostEqual(result["selected_target_local_pose"]["x"], 0.1)
        self.assertTrue(result["certificate"]["accepted"])


if __name__ == "__main__":
    unittest.main()
