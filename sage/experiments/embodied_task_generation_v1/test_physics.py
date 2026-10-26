import unittest
from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation
from .physics import evaluate,quat,numerical_comparison
from sage.experiments.embodied_scene_quality_v1.contracts import Rejected


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        nominal=quat(Rotation.from_euler('y',90,degrees=True));q=np.r_[0.,0.,.02,nominal]
        self.task=dict(state_size=14,nominal_quaternion_wxyz=nominal.tolist(),goal=[0,0,.02],
            target_dimensions_m=[.04,.17,.24],support_pose=np.eye(4).tolist(),roi_xy_m=[[-.2,-.2],[.2,.2]],
            support_bounds_local_m=[[-1,-1,-.1],[1,1,0]],physical_prior=dict(mass_kg=.25))
        p=dict(duration_s=2.5,stable_tail_s=1.,initial_penetration_m_max=1e-6,max_target_penetration_m=.003,
            max_speed_m_s=.03,max_angular_speed_rad_s=.2,orientation_error_deg_max=5,xy_drift_m_max=.01,
            goal_xy_tolerance_m=.04,containment_margin_m=.005,mean_support_weight_ratio=[.5,1.5],base_dt_s=.001,refined_dt_s=.0005)
        self.protocol=dict(physics=p,numerical=dict(replay_atol=1e-12,position_tolerance_m=.0025,orientation_tolerance_deg=1.,speed_tolerance_m_s=.01,first_contact_tolerance_s=.02))
        self.initial=dict(qpos=q.tolist(),complete_state=np.r_[0.,q,np.zeros(6)].tolist(),penetration_m=0.)
        self.attempt=dict(new_physics_steps=2500,dt_s=.001,status='completed',description=dict(target_geom_ids=[2],bottom_geom_ids=[1]))
        t=np.arange(1,2501)*.001;qs=np.tile(q,(2500,1));vs=np.zeros((2500,6))
        self.raw=dict(time=t,qpos=qs,qvel=vs,full_state=np.vstack([self.initial['complete_state'],np.c_[t,qs,vs]]),
            contacts=np.array([[i,1,2,0,0,0,0,0,1,.25*9.81,0,0,0,0,0] for i in range(2500)]),
            contact_frames=np.tile(np.array([0.,0.,1.,1.,0.,0.,0.,1.,0.]),(2500,1)),warnings=np.zeros(8))

    def value(self):return evaluate(self.raw,self.initial,self.attempt,self.task,self.protocol)

    def test_flat_nominal_passes(self):self.assertTrue(self.value()['passed'])

    def test_upright_metric_cannot_substitute(self):
        self.task['nominal_quaternion_wxyz']=[1,0,0,0]
        self.assertFalse(self.value()['conditions']['orientation'])

    def test_motion_rejected(self):
        self.raw['qvel'][:,0]=.04;self.raw['full_state'][1:,8]=.04
        self.assertFalse(self.value()['passed'])

    def test_missing_support_rejected(self):
        self.raw['contacts']=np.zeros((0,15));self.raw['contact_frames']=np.zeros((0,9))
        self.assertFalse(self.value()['passed'])

    def test_state_tampering_rejected(self):
        self.raw['qpos'][-1,0]=.1
        with self.assertRaises(Rejected):self.value()

    def test_nonfinite_rejected(self):
        self.raw['qvel'][0,0]=np.nan
        with self.assertRaises(Rejected):self.value()

    def test_contact_frame_tampering_rejected(self):
        self.raw['contact_frames'][0,2]=-1
        with self.assertRaises(Rejected):self.value()

    def test_replay_compares_complete_frames(self):
        original=self.value();copy=deepcopy(self.raw)
        self.assertTrue(numerical_comparison(self.raw,copy,original,original,self.protocol,replay=True)['passed'])
        copy['contact_frames'][0,3]+=.001
        self.assertFalse(numerical_comparison(self.raw,copy,original,original,self.protocol,replay=True)['passed'])


if __name__=='__main__':unittest.main()
