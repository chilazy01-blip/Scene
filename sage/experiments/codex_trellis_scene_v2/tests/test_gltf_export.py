from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import trimesh

from sage.experiments.codex_trellis_scene_v2.gltf_export import (
    export_z_up_scene_glb,
    gltf_y_up_to_z_up_matrix,
)


class GltfExportTest(unittest.TestCase):
    def test_z_up_scene_is_encoded_y_up_and_recovers_for_blender(self) -> None:
        scene = trimesh.Scene()
        floor = trimesh.creation.box(extents=(4.0, 3.0, 0.04))
        floor.apply_translation((0.0, 0.0, -0.02))
        scene.add_geometry(floor, node_name="floor", geom_name="floor_geometry")
        original_bounds = scene.bounds.copy()

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "scene.glb"
            report = export_z_up_scene_glb(scene, output)
            encoded = trimesh.load(output, force="scene")

        self.assertTrue(report["ok"])
        self.assertTrue(np.allclose(scene.bounds, original_bounds))
        self.assertTrue(np.allclose(encoded.extents, (4.0, 0.04, 3.0), atol=1e-6))

        encoded.apply_transform(gltf_y_up_to_z_up_matrix())
        self.assertTrue(np.allclose(encoded.extents, (4.0, 3.0, 0.04), atol=1e-6))
        self.assertTrue(np.allclose(encoded.bounds, original_bounds, atol=1e-6))

    def test_existing_output_requires_explicit_overwrite(self) -> None:
        scene = trimesh.Scene(trimesh.creation.box())
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "scene.glb"
            export_z_up_scene_glb(scene, output)
            with self.assertRaises(FileExistsError):
                export_z_up_scene_glb(scene, output)


if __name__ == "__main__":
    unittest.main()
