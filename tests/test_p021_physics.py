"""Tiny mathematical GLBs only; these are never experiment furniture assets."""

import json
from pathlib import Path
import struct
import tempfile
import unittest
from copy import deepcopy

import mujoco
import numpy as np

from sage.experiments.codex_trellis_scene_v2 import p021_physics as physics


VERTICES = np.asarray([[-.5, -.5, -.5], [.5, -.5, -.5], [.5, .5, -.5], [-.5, .5, -.5],
                       [-.5, -.5, .5], [.5, -.5, .5], [.5, .5, .5], [-.5, .5, .5]], dtype="<f4")
FACES = np.asarray([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
                    [1, 2, 6], [1, 6, 5], [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]], dtype="<u2")


def spec(method="A_support_priority", **simulation):
    return {"schema": "p021-physics-scene-spec/v1", "run_id": "tiny_unit_test_only", "method": method,
            "floor_mu": .3, "objects": [{"id": "tiny", "inventory_id": "synthetic_unit_test_only", "x": 2., "y": 2., "z": 0., "yaw": 0.}],
            "room": {"width": 6., "length": 5., "height": 2.8}, "parameter_origin": "designed_test_coefficient",
            "measured_asset_friction": None, "development": True,
            "simulation": {"dt": .002, "settle_s": .2, "action_s": 2., "initial_velocity_m_s": [1.5, 0, 0], "sample_interval_s": .1, **simulation}}


def fixture(path, *, object_id="tiny", object_transform=None, floor_transform=None, extra=False):
    binary = VERTICES.tobytes() + FACES.tobytes()
    floor = np.diag([6., 5., .05, 1.])
    floor[:3, 3] = [3., 2.5, -.025]
    obj = np.diag([1., .8, .3, 1.])
    obj[:3, 3] = [2., 2., .15]
    obj = obj if object_transform is None else object_transform
    floor = floor if floor_transform is None else floor_transform
    z_to_gltf = np.linalg.inv(physics.GLTF_TO_Z)
    nodes = [{"name": "floor", "mesh": 0, "matrix": (z_to_gltf @ floor).T.reshape(-1).tolist(), "extras": {"floor_material_id": "unit_test"}},
             {"name": object_id + "_root", "matrix": (z_to_gltf @ obj).T.reshape(-1).tolist(), "children": [2], "extras": {"scene_object_id": object_id}},
             {"name": object_id + "_geometry", "mesh": 0}]
    roots = [0, 1]
    if extra:
        nodes.append({"name": "unexpected_root", "mesh": 0, "extras": {"scene_object_id": "extra"}})
        roots.append(3)
    document = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": roots}], "nodes": nodes,
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
                "buffers": [{"byteLength": len(binary)}],
                "bufferViews": [{"buffer": 0, "byteLength": VERTICES.nbytes}, {"buffer": 0, "byteOffset": VERTICES.nbytes, "byteLength": FACES.nbytes}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(VERTICES), "type": "VEC3"},
                              {"bufferView": 1, "componentType": 5123, "count": FACES.size, "type": "SCALAR"}]}
    write_glb(path, document, binary)
    return document, binary


def write_glb(path, document, binary):
    text = json.dumps(document).encode()
    text += b" " * (-len(text) % 4)
    binary += b"\0" * (-len(binary) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(text) + len(binary)) +
                     struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary)


class P021PhysicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scene = self.root / "fixture.glb"
        fixture(self.scene)

    def test_axis_ancestor_rotation_and_nonuniform_scale_baked_once(self):
        angle = np.deg2rad(31)
        transform = np.eye(4)
        transform[:3, :3] = np.array([[np.cos(angle), -np.sin(angle), 0], [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]) @ np.diag([1.7, .4, .8])
        transform[:3, 3] = [2.2, 3.1, .4]
        fixture(self.scene, object_transform=transform)
        groups, floor = physics._geometry(self.scene, spec())
        expected = VERTICES @ transform[:3, :3].T + transform[:3, 3]
        np.testing.assert_allclose(groups["tiny"][0]["vertices"], expected, atol=1e-12)
        np.testing.assert_allclose(floor["world_bounds_z_up"], [[0, 0, -.05], [6, 5, 0]], atol=1e-12)
        np.testing.assert_allclose(groups["tiny"][0]["binding"]["world_matrix_z_up"], transform, atol=1e-12)

    def test_mass_frame_invariant_under_rigid_motion_scale_shear_and_reflection(self):
        from scipy.spatial.transform import Rotation
        for reflected in (False, True):
            local = np.array([[1.7, .1, 0], [0, .4, .03], [0, 0, .8]])
            if reflected:
                local[:, 0] *= -1
            reference = None
            for angles in ([0, 0, 0], [0, 0, 45], [0, 0, 90], [24, -17, 31]):
                rotation = Rotation.from_euler('xyz', angles, degrees=True).as_matrix()
                transform = np.eye(4)
                transform[:3, :3] = rotation @ local
                transform[:3, 3] = [2.2, 2.1, 1.]
                fixture(self.scene, object_transform=transform)
                groups, _ = physics._geometry(self.scene, spec())
                body, points, extents = physics.object_mass_frame(groups['tiny'])
                if reference is None:
                    reference = body, points, extents
                np.testing.assert_allclose(extents, reference[2], atol=1e-12)
                np.testing.assert_allclose(points, reference[1], atol=1e-12)
                np.testing.assert_allclose(body[:3, :3], rotation @ reference[0][:3, :3], atol=1e-12)
                np.testing.assert_allclose(points @ body[:3, :3].T + body[:3, 3],
                    groups['tiny'][0]['vertices'], atol=1e-12)

    def test_complete_state_restores_exact_midrun_continuation_and_rejects_wrong_model(self):
        output = self.root/'restore'
        physics.run_physics(self.scene, spec(dt=.001), output)
        with np.load(output/'dense_state.npz') as saved:
            index = 532
            model, data = physics.restore_saved_state(output/'model.xml', output/'dense_state.npz', index)
            for offset in range(1, 31):
                mujoco.mj_step(model, data)
                mujoco.mj_forward(model, data)
                state = np.empty(mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_INTEGRATION))
                mujoco.mj_getState(model, data, state, mujoco.mjtState.mjSTATE_INTEGRATION)
                np.testing.assert_array_equal(state, saved['integration_state'][index+offset])
        (output/'model.xml').write_text((output/'model.xml').read_text()+'\n')
        with self.assertRaisesRegex(ValueError, 'model differs'):
            physics.restore_saved_state(output/'model.xml', output/'dense_state.npz', index)

    def test_compiled_mass_and_world_inertia_rotate_as_one_rigid_object(self):
        from scipy.spatial.transform import Rotation
        tensors=[]
        for angle in (0,45):
            rotation=Rotation.from_euler('z',angle,degrees=True).as_matrix()
            transform=np.eye(4);transform[:3,:3]=rotation@np.diag([1.,.8,.3])
            transform[:3,3]=[2.,2.,.15]
            fixture(self.scene,object_transform=transform)
            output=self.root/('rotated_'+str(angle))
            physics.run_physics(self.scene,spec(),output)
            obj=physics.verify_physics_binding(self.scene,output/'physics_binding.json')['objects']['tiny']
            self.assertAlmostEqual(obj['compiled']['mass_kg'],19.2,places=10)
            inertial=Rotation.from_quat(np.array(obj['compiled']['inertial_quaternion_wxyz'])[[1,2,3,0]]).as_matrix()
            world=np.array(obj['initial_body_matrix_z_up'])[:3,:3]@inertial
            tensor=world@np.diag(obj['compiled']['diagonal_inertia_kg_m2'])@world.T
            if tensors:
                np.testing.assert_allclose(tensor,rotation@tensors[0]@rotation.T,atol=1e-12)
            tensors.append(tensor)

    def test_engineering_failure_propagates_and_is_independently_rejected(self):
        from sage.experiments.codex_trellis_scene_v2.p021_physics_analysis import engineering_result_check
        result = physics.run_physics(self.scene, spec(), self.root/'failure_injection')
        self.assertIs(physics.require_engineering_success(result), result)
        self.assertTrue(engineering_result_check(result))
        for kind in ('status', 'warning', 'gate', 'missing_gate', 'failure'):
            altered = deepcopy(result)
            if kind=='status':
                altered['status']='completed_with_engineering_failures'
            elif kind=='warning':
                altered['simulator_warnings']=[{'warning_id':0,'count':1}]
            elif kind=='gate':
                altered['engineering_gates']['all_states_finite']=False
            elif kind=='missing_gate':
                del altered['engineering_gates']['no_simulator_warnings']
            else:
                altered['failures']=['injected']
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'engineering failure'):
                physics.require_engineering_success(altered)
            self.assertFalse(engineering_result_check(altered))

    def test_numerical_diagnostics_run_even_for_engineering_failure(self):
        settings = spec(initial_velocity_m_s=[8., 0, 0])
        result = physics.run_physics(self.scene, settings, self.root/'outside_room')
        self.assertEqual(result['status'], 'completed_with_engineering_failures')
        self.assertFalse(result['engineering_gates']['trajectory_inside_room'])
        self.assertEqual(len(result['numerical_diagnostics']['grids']), 3)
        self.assertEqual(len(result['numerical_diagnostics']['comparisons']), 3)

    def test_actual_floor_rejects_changed_axes_or_sloped_geometry(self):
        floor = np.diag([6., 5., .05, 1.])
        floor[2, 0] = .1
        floor[:3, 3] = [3., 2.5, -.025]
        fixture(self.scene, floor_transform=floor)
        with self.assertRaisesRegex(ValueError, "floor is not an axis-aligned"):
            physics._geometry(self.scene, spec())
        document, binary = fixture(self.scene)
        document["nodes"][0]["matrix"] = np.eye(4).T.reshape(-1).tolist()
        write_glb(self.scene, document, binary)
        with self.assertRaisesRegex(ValueError, "floor bounds disagree"):
            physics._geometry(self.scene, spec())

    def test_missing_extra_and_conflicting_exact_ids_reject(self):
        for object_id, extra in (("missing", False), ("tiny", True)):
            with self.subTest(object_id=object_id, extra=extra):
                fixture(self.scene, object_id=object_id, extra=extra)
                with self.assertRaisesRegex(ValueError, "unexpected object ID"):
                    physics._geometry(self.scene, spec())
        document, binary = fixture(self.scene)
        document["nodes"][2]["extras"] = {"scene_object_id": "different"}
        write_glb(self.scene, document, binary)
        with self.assertRaisesRegex(ValueError, "conflicting ancestor"):
            physics._geometry(self.scene, spec())

    def test_hull_is_deterministic_and_preserves_visual_extrema(self):
        points = np.concatenate([VERTICES, [[0, 0, 0], [0, .2, 0]], VERTICES])
        a, af = physics._hull(points)
        b, bf = physics._hull(points[::-1])
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(af, bf)
        self.assertEqual(len(a), 8)
        matrix = np.array([[.7, .2, -.1], [.1, -.9, .2], [.4, .3, .8]])
        np.testing.assert_allclose((a @ matrix).min(axis=0), (points @ matrix).min(axis=0))
        np.testing.assert_allclose((a @ matrix).max(axis=0), (points @ matrix).max(axis=0))

    def test_declared_contact_combination_reaches_runtime_in_mujoco_334(self):
        """Read actual contact fields; configuring a low floor alone stays max .9."""
        for method, expected in (("automatic", .9), ("priority", .3), ("pair", .3)):
            with self.subTest(method=method):
                priority = 1 if method == "priority" else 0
                pair = '<contact><pair geom1="floor" geom2="body_geom" condim="3" friction=".3 .3 .05 .001 .001" solref=".01 1" solimp=".9 .95 .001"/></contact>' if method == "pair" else ""
                xml = f'''<mujoco><option timestep=".002"><flag multiccd="enable" nativeccd="enable"/></option>
                    <default><geom condim="3" friction=".9 .05 .001" solref=".01 1" solimp=".9 .95 .001"/></default>
                    <worldbody><geom name="floor" type="plane" size="5 5 .1" friction=".3 .05 .001" priority="{priority}"/>
                    <body pos="0 0 .049"><freejoint/><geom name="body_geom" type="sphere" size=".05"/></body></worldbody>{pair}</mujoco>'''
                model = mujoco.MjModel.from_xml_string(xml)
                data = mujoco.MjData(model)
                mujoco.mj_forward(model, data)
                self.assertGreater(data.ncon, 0)
                self.assertEqual(data.contact[0].dim, 3)
                np.testing.assert_allclose(data.contact[0].friction, [expected, expected, .05, .001, .001], atol=1e-12)
                np.testing.assert_allclose(data.contact[0].solref, [.01, 1], atol=1e-12)
                np.testing.assert_allclose(data.contact[0].solimp, [.9, .95, .001, .5, 2], atol=1e-12)

    def test_real_mesh_dynamics_control_priority_pair_and_rigid_visual_delta(self):
        runs = {}
        for method in ("B0_bound_control", "A_support_priority", "B_explicit_pairs"):
            output = self.root / method
            result = physics.run_physics(self.scene, spec(method), output)
            self.assertEqual(result["status"], "completed", result["failures"])
            self.assertFalse(result["external_physics_validated"])
            binding = physics.verify_physics_binding(self.scene, output / "physics_binding.json")
            self.assertEqual(binding["compiled_parameters"]["options"]["integrator"], int(mujoco.mjtIntegrator.mjINT_RK4))
            self.assertTrue(binding["compiled_parameters"]["options"]["nativeccd_enabled"])
            self.assertTrue(binding["compiled_parameters"]["options"]["multiccd_enabled"])
            self.assertLess(binding["objects"]["tiny"]["compiled"]["hull_vertex_world_max_error_m"], 1e-5)
            self.assertEqual(len(binding["compiled_parameters"]["pairs"]), int(method == "B_explicit_pairs"))
            trajectory = json.loads((output / "trajectory.json").read_text())
            self.assertEqual(len([frame for frame in trajectory["frames"] if frame["phase"] == "initial"]), 1)
            action_frames = [frame for frame in trajectory["frames"] if frame["phase"] == "action"]
            np.testing.assert_allclose([frame["action_time_s"] for frame in action_frames], np.arange(21) * .1, atol=1e-12)
            initial = np.asarray(binding["objects"]["tiny"]["initial_body_matrix_z_up"])
            final = np.asarray(action_frames[-1]["bodies"]["tiny"]["matrix_world_z_up"])
            original_visual = np.asarray(binding["objects"]["tiny"]["mesh_binding"][0]["world_matrix_z_up"])
            visual_final = final @ np.linalg.inv(initial) @ original_visual
            points_from_visual = VERTICES @ visual_final[:3, :3].T + visual_final[:3, 3]
            original_world = VERTICES @ original_visual[:3, :3].T + original_visual[:3, 3]
            points_from_body = (original_world - initial[:3, 3]) @ final[:3, :3].T + final[:3, 3]
            np.testing.assert_allclose(points_from_visual, points_from_body, atol=1e-12)
            with np.load(output / "dense_state.npz", allow_pickle=False) as dense:
                np.testing.assert_allclose(dense["world_bounds_z_up"][-1, 0], [points_from_visual.min(axis=0), points_from_visual.max(axis=0)], atol=1e-12)
                self.assertEqual(len(dense["time_s"]), 1102)
                self.assertEqual(dense["object_ids"].tolist(), ["tiny"])
                impulse_index = np.flatnonzero(dense["action_time_s"] == 0)[0]
                np.testing.assert_array_equal(dense["qvel"][impulse_index, 2:], dense["qvel"][impulse_index - 1, 2:])
                np.testing.assert_allclose(dense["qvel"][impulse_index, :2], [1.5, 0], atol=1e-12)
            runs[method] = result
        control = runs["B0_bound_control"]["metrics"]["objects"]["tiny"]["forward_displacement_m"]
        priority = runs["A_support_priority"]["metrics"]["objects"]["tiny"]["forward_displacement_m"]
        pair = runs["B_explicit_pairs"]["metrics"]["objects"]["tiny"]["forward_displacement_m"]
        self.assertGreater(priority, 1.5 * control)
        self.assertAlmostEqual(priority, pair, delta=.002)

    def test_actual_implicitfast_mesh_dynamics_preserve_geometry_and_contact_mapping(self):
        results, hull_hashes = {}, set()
        for method in sorted(physics.METHODS):
            output = self.root / (method + "_implicitfast")
            result = physics.run_physics(self.scene, spec(method, integrator="implicitfast", action_s=.8), output)
            self.assertEqual(result["status"], "completed", result["failures"])
            binding = physics.verify_physics_binding(self.scene, output / "physics_binding.json")
            self.assertEqual(binding["compiled_parameters"]["options"]["integrator"], int(mujoco.mjtIntegrator.mjINT_IMPLICITFAST))
            hull_hashes.add(binding["objects"]["tiny"]["collider"]["artifact"]["sha256"])
            self.assertEqual(result["contact_summary"]["parameter_mismatch_records"], 0)
            self.assertTrue(result["engineering_gates"]["actual_target_contacts_observed"])
            results[method] = result["metrics"]["objects"]["tiny"]["forward_displacement_m"]
        self.assertEqual(len(hull_hashes), 1)
        self.assertGreater(results["A_support_priority"], 1.5 * results["B0_bound_control"])
        self.assertAlmostEqual(results["A_support_priority"], results["B_explicit_pairs"], delta=.002)
        for unsupported in ("Euler", "implicit", "RK5", None):
            with self.subTest(unsupported=unsupported), self.assertRaisesRegex(ValueError, "integrator must be"):
                physics._validate_spec(spec(integrator=unsupported))

    def test_binding_mutation_failures_and_output_preservation(self):
        output = self.root / "attempt"
        short = spec(settle_s=.02, action_s=.1)
        physics.run_physics(self.scene, short, output)
        binding_path = output / "physics_binding.json"
        binding = json.loads(binding_path.read_text())
        original_binding = binding_path.read_bytes()
        binding["objects"]["tiny"]["initial_body_matrix_z_up"][0][3] += .01
        binding_path.write_text(json.dumps(binding))
        with self.assertRaisesRegex(ValueError, "body frame changed"):
            physics.verify_physics_binding(self.scene, binding_path)
        binding_path.write_bytes(original_binding)
        changed_transform = json.loads(original_binding)
        changed_transform["objects"]["tiny"]["mesh_binding"][0]["world_matrix_z_up"][1][3] += .02
        binding_path.write_text(json.dumps(changed_transform))
        with self.assertRaisesRegex(ValueError, "mesh/transform binding changed"):
            physics.verify_physics_binding(self.scene, binding_path)
        binding_path.write_bytes(original_binding)
        collider_path = Path(binding["objects"]["tiny"]["collider"]["artifact"]["path"])
        original_collider = collider_path.read_bytes()
        collider_path.write_bytes(original_collider + b"mutated")
        with self.assertRaisesRegex(ValueError, "file content changed"):
            physics.verify_physics_binding(self.scene, binding_path)
        collider_path.write_bytes(original_collider)
        original_scene = self.scene.read_bytes()
        self.scene.write_bytes(original_scene + b"mutated")
        with self.assertRaisesRegex(ValueError, "file content changed"):
            physics.verify_physics_binding(self.scene, binding_path)
        self.scene.write_bytes(original_scene)
        previous = (output / "physics_result.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already contains an attempt"):
            physics.run_physics(self.scene, short, output)
        self.assertEqual((output / "physics_result.json").read_bytes(), previous)

    def test_upstream_hash_and_invalid_parameters_fail_before_simulation(self):
        bound_spec = spec()
        bound_spec["scene_glb"] = physics._bound(self.scene)
        self.scene.write_bytes(self.scene.read_bytes() + b"mutation")
        with self.assertRaisesRegex(ValueError, "file content changed"):
            physics.run_physics(self.scene, bound_spec, self.root / "hash_failure")
        failure = json.loads((self.root / "hash_failure" / "physics_result.json").read_text())
        self.assertEqual(failure["stage"], "validate_input")
        for bad in (-.1, 0, float("inf"), float("nan")):
            invalid = spec()
            invalid["floor_mu"] = bad
            with self.assertRaisesRegex(ValueError, "positive finite"):
                physics._validate_spec(invalid)
        invalid = spec()
        invalid["development"] = False
        with self.assertRaisesRegex(ValueError, "upstream final scene binding"):
            physics._validate_spec(invalid)
        invalid = spec(dt=.02)
        with self.assertRaisesRegex(ValueError, "time-constant"):
            physics._validate_spec(invalid)


if __name__ == "__main__":
    unittest.main()
