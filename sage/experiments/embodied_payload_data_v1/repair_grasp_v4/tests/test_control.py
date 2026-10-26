import unittest
from ..feedback import BoundedBias
from ..progress import CoordinatedPath, ControlRejected
from ..intent import HandIntent, GraspGate


class ControlTests(unittest.TestCase):
    def test_preload_does_not_integrate_historical_open_pose_error(self):
        controller=BoundedBias([0.,.22])
        controller.integration_enabled=[True,False]
        for _ in range(100):
            command,meta=controller.step([0.,.22],[0.,.002],[.043,.105])
        self.assertEqual(controller.bias[1],0.)
        self.assertAlmostEqual(command[1],.22)
        self.assertLess(controller.bias[0],0.)
        self.assertLessEqual(meta['peak_acceleration'],4.+1e-8)

    def test_preload_progress_keeps_real_hand_error_visible(self):
        path=CoordinatedPath([[0.,0.],[.01,.22]],tracking_waypoints=[[0.,0.],[.01,.002]])
        path.tracking_indices=(0,)
        for _ in range(300):
            actual=[path.expected_actual[0],.105]
            path.step(actual,lambda *a:True)
            if path.finished:break
        self.assertTrue(path.finished)
        self.assertGreater(abs(actual[1]-path.expected_actual[1]),.04)
        gate=GraspGate()
        result=gate.observe(time=0.,semantics='integrated_step_world_force',contacts={'left':0,'right':1},
            upward_load=-2.,weight=2.4525,relative_displacement=0.,relative_speed=0.,lift=0.,
            arm_tracking_ok=True,corridor_passed=True,force_limits_passed=True)
        self.assertFalse(result['allow_full_lift'])

    def test_arm_tracking_timeout_is_not_masked_by_hand_intent(self):
        path=CoordinatedPath([[0.,0.],[.1,.22]])
        path.tracking_indices=(0,)
        with self.assertRaisesRegex(ControlRejected,'tracking_timeout|path_stagnation'):
            for _ in range(110):path.step([path.expected_actual[0]+.05,.1],lambda *a:True)

    def test_external_grasp_pause_cannot_self_reset_on_good_joint_tracking(self):
        path=CoordinatedPath([[0.],[.1]])
        path.external_pause=True
        with self.assertRaisesRegex(ControlRejected,'tracking_timeout|path_stagnation'):
            for _ in range(110):path.step([0.],lambda *a:True)

    def test_external_pause_release_requires_stable_recovery(self):
        path=CoordinatedPath([[0.],[.1]])
        path.external_pause=True;path.step([0.],lambda *a:True)
        path.external_pause=False
        for _ in range(4):
            _,meta=path.step([0.],lambda *a:True)
            self.assertTrue(meta['braking'])
        _,meta=path.step([0.],lambda *a:True)
        self.assertFalse(meta['braking'])
