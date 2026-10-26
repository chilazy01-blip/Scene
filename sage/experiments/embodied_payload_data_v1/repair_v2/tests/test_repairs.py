import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from .. import METHOD_VERSION, QUALITY_VERSION
from ..quality import QualityContract, support_window, phase_contacts, foot_transients, continuous_transport, contact_dynamics
from ..progress import CoordinatedPath, ControlRejected, validate_ik, ManipulationState, grasp_state
from ..dataset import EpisodeSidecars, command_stream, masked_mse, validate_split
from ..admission import AdmissionError, check, claim, sha
from ..pipeline import run_operation
from ..observations import visual_visibility
from ..observations import foot_side
from types import SimpleNamespace

class ControlTests(unittest.TestCase):

    def test_checkpoint_requires_fresh_integrated_stable_observations(self):
        from ..controller import TaskController
        controller=TaskController.__new__(TaskController)
        data=SimpleNamespace(qpos=np.zeros(57),qvel=np.zeros(55))
        data.qpos[2]=.75
        controller.qmap=np.arange(7,50);controller.upper=np.arange(12,43)
        controller.check_deadline=lambda:None
        controller.leg_correction=np.zeros(12)
        controller._release=lambda d:setattr(controller,'phase','hold')
        controller._planned_state=lambda:data.qpos.copy()
        controller.height_bias=0.;controller.current_phase=0.
        controller.begin_checkpoint(data,np.zeros(43),'release')
        evidence=dict(time=0.,force_semantics='integrated_step_world_force',foot_load=dict(left=100.,right=100.),hand_contacts=0,hand_contacts_by_side=dict(left=0,right=0),board_vertical_load=2.45,weight=2.45,bottom_margin=.01,object_linear=0.,object_angular=0.)
        original=data.qpos.copy()
        for i in range(9):
            evidence['time']=i*.02
            goal,meta=controller.target(data,evidence)
            self.assertTrue(controller.preparing)
            np.testing.assert_array_equal(goal['target_upper_body_pose'],np.zeros(31))
        with self.assertRaisesRegex(ControlRejected,'stale_checkpoint_observation'):
            controller.target(data,evidence)
        evidence['time']=.18
        controller.target(data,evidence)
        self.assertFalse(controller.preparing)
        np.testing.assert_array_equal(data.qpos,original)

    def test_foot_identity_uses_body_not_generic_geom_name(self):
        query=SimpleNamespace(m=SimpleNamespace(geom_bodyid=[13,29,13,7]),
                              feet={'left':13,'right':29},names=['g0','g1','g2','g3'])
        self.assertEqual(foot_side(query,0),'left')
        self.assertEqual(foot_side(query,1),'right')
        self.assertEqual(foot_side(query,2),'left')
        with self.assertRaises(ValueError):foot_side(query,3)

    def test_actuator_preload_is_not_mistaken_for_tracking_error(self):
        path=CoordinatedPath([[.3,0],[.5,.2]],tracking_waypoints=[[0,0],[.2,.2]])
        for _ in range(500):
            actual=path.expected_actual.copy()
            command,meta=path.step(actual,lambda *args:True)
            self.assertAlmostEqual(meta['lag'],0.)
            self.assertLessEqual(abs(command[0]-path.expected_actual[0]-.3),1e-8)
            if meta['finished']:break
        self.assertTrue(path.finished)
        with self.assertRaises(ControlRejected):
            for _ in range(101):path.step([-.2,-.2],lambda *args:True)

    def test_all_channels_share_progress_and_derivative_bounds(self):
        target = np.linspace(-0.3, 0.6, 31)
        path = CoordinatedPath(np.stack([np.zeros(31), target, np.zeros(31)]))
        actual = np.zeros(31)
        last = actual.copy()
        v = np.zeros(31)
        brake_observed = False
        for i in range(1500):
            observed = actual - 0.1 if 15 <= i < 23 else actual
            command, meta = path.step(observed, lambda a, b, stop: True)
            command = np.asarray(command)
            vn = (command - last) / 0.02
            self.assertLessEqual(np.max(np.abs(vn)), 1.0 + 1e-07)
            self.assertLessEqual(np.max(np.abs(vn - v)) / 0.02, 4.0 + 1e-07)
            self.assertLess(np.ptp(command[target != 0] / target[target != 0]), 1e-08)
            brake_observed |= meta.get('braking', False)
            actual = last = command
            v = vn
            if meta['finished']:
                break
        self.assertTrue(path.finished)
        self.assertTrue(brake_observed)
        np.testing.assert_allclose(command, 0.0, atol=1e-07)

    def test_bad_ik_and_stopping_corridor_rejected(self):
        bad = {s: dict(position=0.07, rotation=0.0, condition=10.0) for s in ('left', 'right')}
        with self.assertRaises(ControlRejected):
            validate_ik(bad)
        path = CoordinatedPath([[0.0, 0.0], [1.0, 0.5]])
        with self.assertRaises(ControlRejected):
            path.step([0.0, 0.0], lambda *args: False)
        np.testing.assert_array_equal(path.last, [0.0, 0.0])

    def test_release_needs_actual_support_and_lost_grasp_exits(self):
        state = ManipulationState()
        obs = dict(grasped=True, slipped=False, lifted=True, at_standoff=False, settled=False, placement_ready=False, supported=False, released=False, withdrawal_done=False, terminal_passed=False)
        self.assertEqual(state.update(**obs), 'carry')
        obs['grasped'] = False
        with self.assertRaises(ControlRejected):
            state.update(**obs)
        self.assertFalse(grasp_state(1, 1, 0.02, 0.1, 0.0, 2.45, displacement_limit=0.005, speed_limit=0.02)['grasped'])

class DataTests(unittest.TestCase):

    def test_tail_padding_never_executes_or_contributes_to_loss(self):
        q = np.arange(4 * 43, dtype=float).reshape(2, 2, 43)
        q[-1, -1] = np.nan
        mask = np.array([[1, 1], [1, 0]], bool)
        times = np.array([[0.0, 0.02], [0.04, np.nan]])
        commands = list(command_stream(q, times, mask))
        self.assertEqual(len(commands), 3)
        self.assertTrue(all((c['duration'] == 0.02 for c in commands)))
        self.assertEqual(masked_mse(q, q, mask), 0.0)
        with self.assertRaises(ValueError):
            list(command_stream(q, times, np.array([[1, 0], [1, 0]])))

    def test_two_episodes_restart_frames_without_depth_cross_talk(self):
        import h5py
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            entries = []
            for eid, value in ((7, 1.0), (9, 9.0)):
                path = root / f'{eid}.h5'
                with h5py.File(path, 'w') as f:
                    f['trajectory/timestamp'] = np.array([0.0, 0.04])
                    f['cameras/cam/depth_m'] = np.full((2, 2, 2), value)
                    f['cameras/cam/valid'] = np.ones((2, 2, 2), bool)
                entries.append(dict(episode_id=eid, path=path.name, sha256=sha(path), quality_version=QUALITY_VERSION, accepted=True, provenance={'test_fixture': True}, rows=2, cameras=['cam']))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps(dict(schema='episode-sidecars/v2', episodes=entries)))
            reader = EpisodeSidecars(manifest)
            for eid, value in ((7, 1.0), (9, 9.0)):
                for frame in range(2):
                    self.assertTrue(np.all(reader.read(eid, frame, frame * 0.04)['depth_m.cam'] == value))
            with self.assertRaises(IndexError):
                reader.read(7, 2, 0.08)
            with self.assertRaises(ValueError):
                reader.read(7, 1, 0.0)
            entries[0]['quality_version'] = 'legacy-half-second'
            manifest.write_text(json.dumps(dict(schema='episode-sidecars/v2', episodes=entries)))
            with self.assertRaises(ValueError):
                EpisodeSidecars(manifest)

    def test_scene_split_leakage(self):
        entries = [dict(episode_id=i, scene_family=str(i), split=s) for i, s in enumerate(('train', 'validation', 'test'))]
        self.assertTrue(validate_split(entries))
        entries[-1]['scene_family'] = '0'
        with self.assertRaises(ValueError):
            validate_split(entries)

    def test_nonblack_image_without_task_information_is_rejected(self):
        frames = [dict(phase='place', rgb_mean=0.5, visible_pixels=dict(object=0, hands=40, support=100)) for _ in range(20)]
        self.assertFalse(visual_visibility(frames, ['place'], 0.2)['passed'])
