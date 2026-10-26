import math
import json
from pathlib import Path
import unittest
from ..feedback import BoundedBias
from ..progress import CoordinatedPath
from ...repair_v2.progress import ControlRejected


class FeedbackTests(unittest.TestCase):
    def test_constant_load_offset_is_rejected_by_feedback(self):
        # Static actuator equilibrium surrogate, not a physical trial. The
        # retained elbow's approximately0.043rad offset is absent from nominal.
        controller=BoundedBias([0.]);observed=.043;errors=[]
        for _ in range(100):
            command,meta=controller.step([0.],[0.],[observed])
            observed=command[0]+.043
            errors.append(abs(observed))
            self.assertLessEqual(meta['peak_velocity'],1.+1e-10)
            self.assertLessEqual(meta['peak_acceleration'],4.+1e-10)
        self.assertLess(errors[-1],.02)
        self.assertLess(errors[-1],errors[0]/3)

    def test_saturation_bounds_and_rejection_do_not_wind_up(self):
        controller=BoundedBias([0.])
        for _ in range(100):controller.step([0.],[1.],[0.],saturated=True)
        self.assertEqual(controller.bias,[0.])
        for _ in range(100):controller.step([0.],[1.],[0.],bounds=[(-1.,0.)])
        self.assertEqual(controller.bias,[0.])
        before=(controller.bias[:],controller.last[:],controller.velocity[:])
        with self.assertRaises(ControlRejected):controller.step([1.],[1.],[0.],safe=lambda c:False)
        self.assertEqual((controller.bias,controller.last,controller.velocity),before)

    def test_full_issued_command_respects_bounds_at_reversals(self):
        controller=BoundedBias([0.,0.])
        for i in range(600):
            nominal=[.2 if i<200 else -.2,.1*math.sin(i*.05)]
            cmd,meta=controller.step(nominal,nominal,controller.last,bounds=[(-.5,.5),(-.5,.5)])
            self.assertLessEqual(meta['peak_velocity'],1.+1e-10)
            self.assertLessEqual(meta['peak_acceleration'],4.+1e-10)
            self.assertTrue(all(abs(x)<=.5 for x in cmd))

    def test_threshold_chatter_cannot_reset_pause(self):
        path=CoordinatedPath([[0.],[1.]])
        with self.assertRaisesRegex(ControlRejected,'tracking_timeout|path_stagnation'):
            for i in range(110):
                path.step([path.expected_actual[0]+(.041 if i%2 else .039)],lambda *x:True)
        self.assertTrue(path.braking)

    def test_recovery_requires_sustained_inner_threshold(self):
        path=CoordinatedPath([[0.],[1.]])
        path.step([.05],lambda *x:True)
        for _ in range(10):
            _,meta=path.step([path.expected_actual[0]+.03],lambda *x:True)
            self.assertTrue(meta['braking'])
        for _ in range(4):
            _,meta=path.step(path.expected_actual,lambda *x:True)
            self.assertTrue(meta['braking'])
        _,meta=path.step(path.expected_actual,lambda *x:True)
        self.assertFalse(meta['braking'])

    def test_inconsistent_zero_command_segment_rejected(self):
        with self.assertRaisesRegex(ValueError,'unactuated_tracking_segment'):
            CoordinatedPath([[0.],[0.]],tracking_waypoints=[[0.],[.1]])
        path=CoordinatedPath([[0.],[0.],[.05]])
        for _ in range(200):
            path.step(path.expected_actual,lambda *x:True)
            if path.finished:break
        self.assertTrue(path.finished)
        self.assertAlmostEqual(path.expected_actual[0],.05)

    def test_feedback_recovers_latched_path_under_constant_disturbance(self):
        path=CoordinatedPath([[0.],[.2]])
        controller=BoundedBias([0.]);observed=.043
        for i in range(600):
            expected=path.expected_actual[:]
            nominal,meta=path.step([observed],lambda *x:True)
            command,_=controller.step(nominal,expected,[observed])
            observed=command[0]+.043
            if meta['finished']:break
        self.assertTrue(path.finished)
        self.assertLess(abs(observed-.2),.04)

    def test_waypoint_end_requires_measured_terminal_tracking(self):
        path=CoordinatedPath([[0.],[.01]])
        for _ in range(200):
            path.step(path.expected_actual,lambda *x:True)
            if path.segment==len(path.path)-1:break
        _,meta=path.step([.04],lambda *x:True)
        self.assertFalse(path.finished)
        self.assertFalse(meta['finished'])
        _,meta=path.step([.01],lambda *x:True)
        self.assertTrue(meta['finished'])

    def test_retained_endpoint_errors_are_unfinished_tracking_not_path_stall(self):
        errors=json.loads(Path(__file__).with_name('terminal_error_fixture.json').read_text())
        path=CoordinatedPath([[0.]*31,[0.]*31])
        path.segment=1
        for row in errors:path.step(row,lambda *x:True)
        self.assertFalse(path.finished)
        self.assertGreater(path.last_lag,.02)
        for _ in range(110):path.step(errors[-1],lambda *x:True)
        self.assertFalse(path.finished)
        with self.assertRaisesRegex(ControlRejected,'tracking_timeout'):
            for _ in range(110):path.step([.05]*31,lambda *x:True)
