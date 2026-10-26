import json
from pathlib import Path
import unittest
from ..intent import HandIntent, GraspGate, GraspRejected


FIXTURE=json.loads(Path(__file__).with_name('grasp_failure_fixture.json').read_text())


def observation(t, **kw):
    row=dict(time=t,semantics='integrated_step_world_force',contacts={'left':1,'right':1},
             upward_load=0.,weight=2.4525,relative_displacement=0.,relative_speed=0.,
             lift=0.,arm_tracking_ok=True,corridor_passed=True,force_limits_passed=True)
    row.update(kw)
    return row


class IntentTests(unittest.TestCase):
    def test_retained_closing_command_cannot_require_open_demo_pose(self):
        for mode in ['position','contact_preload']:
            with self.assertRaises(GraspRejected):
                HandIntent(mode,tuple(FIXTURE['command']),tuple(FIXTURE['expected']))

    def test_preload_feedback_does_not_cancel_grasp_intent(self):
        hand=HandIntent('contact_preload',tuple(FIXTURE['command']))
        self.assertIsNone(hand.integral_error(FIXTURE['actual']))
        self.assertEqual(hand.command,tuple(FIXTURE['command']))

    def test_retained_single_hand_contact_cannot_authorize_lift(self):
        gate=GraspGate()
        for i in range(99):
            result=gate.observe(**observation(i*.02,contacts=FIXTURE['contacts'],upward_load=FIXTURE['upward_load']))
            self.assertFalse(result['allow_probe'])
            self.assertFalse(result['allow_full_lift'])
            self.assertFalse(result['allow_transport'])

    def test_touching_requires_dwell_and_only_allows_bounded_probe(self):
        gate=GraspGate()
        for i in range(4):self.assertFalse(gate.observe(**observation(i*.02))['allow_probe'])
        result=gate.observe(**observation(.08))
        self.assertTrue(result['allow_probe'])
        self.assertFalse(result['allow_full_lift'])
        self.assertFalse(result['allow_transport'])
        self.assertFalse(gate.observe(**observation(.10,lift=.0051))['allow_probe'])

    def test_loaded_full_lift_is_distinct_from_actual_transport(self):
        gate=GraspGate()
        for i in range(5):result=gate.observe(**observation(i*.02,upward_load=2.4525))
        self.assertTrue(result['allow_full_lift'])
        self.assertFalse(result['allow_transport'])
        self.assertTrue(gate.observe(**observation(.10,upward_load=2.4525,lift=.06))['allow_transport'])

    def test_uncalibrated_force_gate_remains_closed(self):
        gate=GraspGate()
        for i in range(10):result=gate.observe(**observation(i*.02,upward_load=2.4525,lift=.06,force_limits_passed=False))
        self.assertFalse(result['allow_probe'])
        self.assertFalse(result['allow_full_lift'])
        self.assertFalse(result['allow_transport'])

    def test_stale_observation_and_query_force_are_rejected(self):
        gate=GraspGate();gate.observe(**observation(0.))
        with self.assertRaisesRegex(GraspRejected,'stale'):gate.observe(**observation(0.))
        with self.assertRaisesRegex(GraspRejected,'integrated'):GraspGate().observe(**observation(0.,semantics='query'))

    def test_slip_resets_dwell_and_revokes_lift(self):
        gate=GraspGate()
        for i in range(5):gate.observe(**observation(i*.02,upward_load=2.4525))
        result=gate.observe(**observation(.10,upward_load=2.4525,relative_displacement=.021))
        self.assertFalse(result['allow_full_lift'])
        self.assertFalse(gate.observe(**observation(.12,upward_load=2.4525))['allow_full_lift'])

    def test_missing_load_transfer_has_bounded_timeout(self):
        gate=GraspGate()
        with self.assertRaisesRegex(GraspRejected,'grasp_load_transfer_timeout'):
            for i in range(110):gate.observe(**observation(i*.02))

    def test_free_space_reference_is_the_retimed_command(self):
        hand=HandIntent('position',(.1,.2),(.1,.2))
        err=hand.integral_error((.08,.19))
        self.assertAlmostEqual(err[0],.02)
        self.assertAlmostEqual(err[1],.01)
