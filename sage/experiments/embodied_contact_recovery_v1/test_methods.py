import unittest
from .methods import release_ready, FeedbackPlace, ObjectPosePlace


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.good={'tilt_deg':1.,'load_fraction':1.,'speed':.001,'angular_speed':.01,'penetration_m':.001}
    def test_support_gate_rejects_saved_toppling_pose(self):
        self.assertFalse(release_ready(self.good|{'tilt_deg':29.79}))
    def test_fingers_cannot_substitute_for_support(self):
        self.assertFalse(release_ready(self.good|{'load_fraction':0.,'finger_contacts':7}))
    def test_transients_and_penetration_rejected(self):
        for key,value in [('speed',.1),('angular_speed',.5),('penetration_m',.0252)]:
            self.assertFalse(release_ready(self.good|{key:value}))
    def test_stable_supported_sample_passes_candidate_control_gate(self):
        self.assertTrue(release_ready(self.good))
    def test_distinct_planner_implementation(self):
        self.assertIsNot(ObjectPosePlace.align,FeedbackPlace.align)
        self.assertNotEqual(ObjectPosePlace.method,FeedbackPlace.method)


if __name__=='__main__':unittest.main()
