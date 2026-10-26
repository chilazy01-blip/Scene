"""Synthetic math/input fixtures only; these are not experiment assets or frames."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from sage.scripts.blender_p021_physics_render import (
    camera_envelope, capture_frames, checked_matrix, file_evidence, graphics_diagnostics,
    read_glb_nodes, rigid_visual_matrix, validate_cpu_mesa_environment, validate_inputs,
    validate_source_ids, validate_visual_mass_frame,
)


def translation(x: float, y: float, z: float) -> np.ndarray:
    result = np.eye(4)
    result[:3, 3] = [x, y, z]
    return result


def rotation_z(angle: float) -> np.ndarray:
    result = np.eye(4)
    result[:2, :2] = [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    return result


class P021RenderMathTest(unittest.TestCase):
    def test_visual_binding_supports_asset_frame_and_still_rejects_wrong_center(self):
        body=translation(2,3,.5)@rotation_z(.7)
        local=np.array([[-1,-.3,-.5],[1,.3,.5],[-1,.3,.5],[1,-.3,-.5]])
        vertices=local@body[:3,:3].T+body[:3,3]
        obj={'initial_body_matrix_z_up':body.tolist(),'metric_box_extents_m':[2.,.6,1.]}
        np.testing.assert_allclose(validate_visual_mass_frame(vertices,obj,'p021-physics-binding/v2'),body)
        with self.assertRaisesRegex(ValueError,'legacy initial body'):
            validate_visual_mass_frame(vertices,obj,'p021-physics-binding/v1')
        obj['initial_body_matrix_z_up'][0][3]+=.01
        with self.assertRaisesRegex(ValueError,'visual metric box'):
            validate_visual_mass_frame(vertices,obj,'p021-physics-binding/v2')

    def test_rigid_delta_preserves_visual_origin_and_nonuniform_scale(self) -> None:
        initial_body = translation(2.2, 1.4, .9)
        initial_visual = translation(.8, 1.1, -.5) @ rotation_z(.4) @ np.diag([2., .5, 3., 1.])
        delta = translation(.3, -.2, .1) @ initial_body @ rotation_z(.2) @ np.linalg.inv(initial_body)
        now = delta @ initial_body
        actual = rigid_visual_matrix(now, initial_body, initial_visual)
        points = np.array([[.3, -.2, .7, 1], [-.9, .8, -.4, 1]]).T
        np.testing.assert_allclose(actual @ points, delta @ initial_visual @ points, atol=1e-12)
        # A COM replacement loses the imported visual pivot, even if its scale is kept.
        incorrect = now @ np.diag([2., .5, 3., 1.])
        self.assertGreater(np.abs(actual @ points - incorrect @ points).max(), .1)
        np.testing.assert_allclose(actual[:3, :3].T @ actual[:3, :3],
                                   initial_visual[:3, :3].T @ initial_visual[:3, :3], atol=1e-12)

    def test_identity_body_delta_keeps_full_imported_transform(self) -> None:
        initial = translation(5, 2, 1) @ rotation_z(-.5)
        visual = translation(4, 1, 0) @ rotation_z(.3) @ np.diag([.5, 2, 3, 1])
        np.testing.assert_allclose(rigid_visual_matrix(initial, initial, visual), visual, atol=1e-12)

    def test_rejects_scaled_reflected_nonfinite_body_transforms(self) -> None:
        for matrix in (np.diag([2., 1., 1., 1.]), np.diag([-1., 1., 1., 1.]), np.full((4, 4), np.nan)):
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                checked_matrix(matrix, "fixture", rigid=True)

    def test_gltf_world_axes_and_parent_scale_are_not_dropped(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "math_fixture.glb"
            document = {"scene": 0, "scenes": [{"nodes": [0]}], "nodes": [
                {"name": "root", "translation": [2, 3, 4], "scale": [2, 3, 4], "children": [1],
                 "extras": {"scene_object_id": "fixture"}},
                {"name": "mesh", "translation": [1, 2, 3], "mesh": 0,
                 "extras": {"scene_object_id": "fixture"}},
            ]}
            encoded = json.dumps(document).encode()
            encoded += b" " * (-len(encoded) % 4)
            path.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(encoded))
                             + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded)
            nodes = read_glb_nodes(path)
            actual = np.array(nodes[1]["world_matrix_z_up"])
            np.testing.assert_allclose(actual[:3, 3], [4, -16, 9])
            np.testing.assert_allclose(np.diag(actual), [2, 4, 3, 1])
            validate_source_ids(nodes, {"fixture"})
            with self.assertRaisesRegex(ValueError, "missing/extra"):
                validate_source_ids(nodes, {"different_id"})

    def test_camera_envelope_depends_only_on_initial_geometry(self) -> None:
        floor = np.array([[0., 0., -.05], [6., 5., 0.]])
        bounds = [[[1.8, 1.1, 0], [2.6, 1.7, 1.8]], [[1.3, 2.9, 0], [3.1, 3.9, .9]]]
        np.testing.assert_allclose(camera_envelope(floor, bounds), [[-.2, -.4, -.05], [6, 5.4, 2.1]])


class P021RenderSoftwareMesaTest(unittest.TestCase):
    ENVIRONMENT = {
        "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe", "CUDA_VISIBLE_DEVICES": "",
        "NVIDIA_VISIBLE_DEVICES": "void", "EGL_PLATFORM": "surfaceless", "__GLX_VENDOR_LIBRARY_NAME": "mesa",
        "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
    }

    def test_requires_explicit_cpu_mesa_environment(self) -> None:
        self.assertTrue(validate_cpu_mesa_environment(self.ENVIRONMENT)["configured_cpu_mesa"])
        for key in self.ENVIRONMENT:
            altered = dict(self.ENVIRONMENT)
            del altered[key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                validate_cpu_mesa_environment(altered)
        for key, value in (("GALLIUM_DRIVER", "iris"), ("CUDA_VISIBLE_DEVICES", "0"),
                           ("MESA_LOADER_DRIVER_OVERRIDE", "nvidia")):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                validate_cpu_mesa_environment(dict(self.ENVIRONMENT, **{key: value}))

    def test_background_api_failure_is_preserved_without_inventing_renderer(self) -> None:
        class UnavailablePlatform:
            @staticmethod
            def renderer_get():
                raise SystemError("GPU functions for drawing are not available in background mode")

            vendor_get = version_get = renderer_get

        actual = graphics_diagnostics(UnavailablePlatform())
        self.assertIsNone(actual["renderer"])
        self.assertIsNone(actual["vendor"])
        self.assertIsNone(actual["version"])
        self.assertFalse(actual["runtime_software_renderer_verified"])
        self.assertEqual(actual["runtime_renderer_status"], "unverified")
        self.assertEqual(actual["errors"]["renderer"], {
            "error_type": "SystemError", "error": "GPU functions for drawing are not available in background mode"})

    def test_available_hardware_renderer_contradiction_still_rejects(self) -> None:
        class Platform:
            @staticmethod
            def renderer_get():
                return "NVIDIA graphics"

            @staticmethod
            def vendor_get():
                return "NVIDIA"

            @staticmethod
            def version_get():
                return "test fixture"

        with self.assertRaisesRegex(ValueError, "contradicted"):
            graphics_diagnostics(Platform())
        Platform.renderer_get = staticmethod(lambda: "llvmpipe (test fixture)")
        actual = graphics_diagnostics(Platform())
        self.assertTrue(actual["runtime_software_renderer_verified"])
        self.assertEqual(actual["renderer"], "llvmpipe (test fixture)")


class P021RenderInputBindingTest(unittest.TestCase):
    def make_fixture(self, directory: str) -> tuple[Path, Path, Path, dict, dict]:
        root = Path(directory)
        scene = root / "fixture.glb"
        scene.write_bytes(b"hash-only fixture; no image/asset acceptance is asserted")
        binding_path = root / "physics_binding.json"
        trajectory_path = root / "trajectory.json"
        body = translation(2.2, 1.4, .9).tolist()
        binding = {"scene_glb": file_evidence(scene), "objects": {"fixture": {"initial_body_matrix_z_up": body}}}
        binding_path.write_text(json.dumps(binding))

        def frame(phase, timestamp, action_timestamp):
            return {"phase": phase, "time_s": timestamp, "action_time_s": action_timestamp,
                    "bodies": {"fixture": {"matrix_world_z_up": deepcopy(body),
                    "linear_velocity_m_s": [0, 0, 0], "angular_velocity_rad_s": [0, 0, 0]}}}

        trajectory = {"scene_glb": file_evidence(scene), "binding": file_evidence(binding_path),
                      "frames": [frame("initial", 0, None)]
                      + [frame("action", 1 + index/10, index/10) for index in range(21)]
                      + [frame("final", 3, 2)]}
        trajectory_path.write_text(json.dumps(trajectory))
        return scene, trajectory_path, binding_path, trajectory, binding

    def test_complete_continuous_trajectory_validates(self) -> None:
        with TemporaryDirectory() as directory:
            scene, trajectory_path, binding_path, _, _ = self.make_fixture(directory)
            _, trajectory, _ = validate_inputs(scene, trajectory_path, binding_path)
            self.assertEqual(len(capture_frames(trajectory)[1]), 21)

    def test_event_sampling_catches_reverse_between_base_frames(self) -> None:
        from sage.experiments.codex_trellis_scene_v2.p021_physics_diagnostics import diagnostic_frames
        t = np.arange(2001)*.001
        linear = np.zeros((len(t),1,3))
        linear[(t >= .344)&(t <= .387),0,0] = -.02
        linear[369,0,0] = -.09
        dense = {'time_s':t+1,'action_time_s':t,'linear_velocity_m_s':linear,
            'angular_velocity_rad_s':np.zeros_like(linear),
            'matrix_world_z_up':np.tile(np.eye(4),(len(t),1,1,1)),
            'world_bounds_z_up':np.zeros((len(t),1,2,3))}
        frames, sampling = diagnostic_frames(dense,['fixture'],
            {'initial_velocity_m_s':[1.5,0,0], 'action_s':2., 'sample_interval_s':.1},0.)
        self.assertIn(.369, sampling['diagnostic_times_s'])
        self.assertLessEqual(len(frames), 5)
        with TemporaryDirectory() as directory:
            _,_,_,trajectory,_ = self.make_fixture(directory)
            trajectory.update(diagnostic_frames=frames,render_sampling=sampling)
            self.assertEqual(len(capture_frames(trajectory)[1]),21)
            trajectory['diagnostic_frames'].pop()
            with self.assertRaisesRegex(ValueError,'diagnostic frame schedule'):
                capture_frames(trajectory)

    def test_v2_render_pose_must_match_dense_state(self) -> None:
        with TemporaryDirectory() as directory:
            scene,trajectory_path,binding_path,trajectory,_=self.make_fixture(directory)
            rows=trajectory['frames'][:-1]
            dense_path=Path(directory)/'dense.npz'
            np.savez(dense_path,object_ids=np.array(['fixture']),time_s=[r['time_s'] for r in rows],
                action_time_s=[-1 if r['action_time_s'] is None else r['action_time_s'] for r in rows],
                **{key:np.array([[r['bodies']['fixture'][key]] for r in rows])
                   for key in ('matrix_world_z_up','linear_velocity_m_s','angular_velocity_rad_s')})
            spec_path=Path(directory)/'spec.json'
            spec_path.write_text(json.dumps({'simulation':{'action_s':2.,'sample_interval_s':.1}}))
            trajectory.update(schema='p021-physics-trajectory/v2',dense_state=file_evidence(dense_path),
                spec=file_evidence(spec_path),render_sampling={'base_action_times_s':list(np.arange(21)*.1)})
            trajectory_path.write_text(json.dumps(trajectory))
            validate_inputs(scene,trajectory_path,binding_path)
            trajectory['frames'][4]['bodies']['fixture']['matrix_world_z_up'][0][3]+=.01
            trajectory_path.write_text(json.dumps(trajectory))
            with self.assertRaisesRegex(ValueError,'differs from dense physics state'):
                validate_inputs(scene,trajectory_path,binding_path)

    def test_mutated_scene_and_binding_hashes_rejected(self) -> None:
        for mutated in ("scene", "binding"):
            with self.subTest(mutated=mutated), TemporaryDirectory() as directory:
                scene, trajectory_path, binding_path, _, _ = self.make_fixture(directory)
                path = scene if mutated == "scene" else binding_path
                path.write_bytes(path.read_bytes() + b" ")
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    validate_inputs(scene, trajectory_path, binding_path)

    def test_missing_and_extra_body_ids_rejected(self) -> None:
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                scene, trajectory_path, binding_path, trajectory, _ = self.make_fixture(directory)
                bodies = trajectory["frames"][3]["bodies"]
                if mutation == "extra":
                    bodies["unbound"] = deepcopy(bodies["fixture"])
                else:
                    bodies.clear()
                trajectory_path.write_text(json.dumps(trajectory))
                with self.assertRaisesRegex(ValueError, "missing/extra body"):
                    validate_inputs(scene, trajectory_path, binding_path)

    def test_missing_duplicate_or_changed_action_times_rejected(self) -> None:
        for mutation in ("missing", "duplicate", "timestamp"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                _, _, _, trajectory, _ = self.make_fixture(directory)
                if mutation == "missing":
                    trajectory["frames"].pop(5)
                elif mutation == "duplicate":
                    trajectory["frames"].insert(5, deepcopy(trajectory["frames"][5]))
                else:
                    trajectory["frames"][5]["action_time_s"] = .405
                with self.assertRaises(ValueError):
                    capture_frames(trajectory)

    def test_initial_body_change_and_nonfinite_velocity_rejected(self) -> None:
        for mutation in ("initial", "velocity"):
            with self.subTest(mutation=mutation), TemporaryDirectory() as directory:
                scene, trajectory_path, binding_path, trajectory, _ = self.make_fixture(directory)
                body = trajectory["frames"][0]["bodies"]["fixture"]
                if mutation == "initial":
                    body["matrix_world_z_up"][0][3] += .1
                else:
                    body["linear_velocity_m_s"][0] = float("nan")
                trajectory_path.write_text(json.dumps(trajectory))
                with self.assertRaises(ValueError):
                    validate_inputs(scene, trajectory_path, binding_path)


if __name__ == "__main__":
    unittest.main()
