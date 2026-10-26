"""Synthetic boundary tests for the real raw-evidence evaluator."""
import unittest
import numpy as np
from .stability import evaluate


class StaticEvidenceTests(unittest.TestCase):
    def fixture(self):
        p={'stability':dict(duration_s=2.5,tail_s=1.,initial_penetration_max_m=1e-6,max_penetration_m=.003,
            non_support_penetration_max_m=.001,orientation_max_deg=5.,xy_drift_max_m=.01,speed_max_m_s=.03,
            angular_speed_max_rad_s=.2,support_margin_m=.005,support_weight_ratio=[.5,1.5])}
        task=dict(support_pose=np.eye(4).tolist(),support_bounds_local_m=[[-.5,-.5,-.1],[.5,.5,0.]],target_dimensions_m=[.1,.1,.2],physical_prior=dict(mass_kg=.25))
        desc=dict(dt_s=.25,runtime_error=None,target_geom_id=1)
        q=np.array([0.,0.,.1,1.,0.,0.,0.]);rows=np.array([[k,2,1,1,0.,0.,0.,0.,1.,.25*9.81,0.,0.,0.,0.,0.] for k in range(1,11)])
        raw=dict(times=np.arange(1,11)*.25,qpos=np.tile(q,(10,1)),qvel=np.zeros((10,6)),states=np.zeros((10,20)),warnings=np.zeros((10,8)),
            initial_qpos=q,initial_contacts=np.empty((0,15)),initial_frames=np.empty((0,9)),contacts=rows,
            frames=np.tile(np.array([[0.,0.,1.],[1.,0.,0.],[0.,1.,0.]]).ravel(),(10,1)))
        return raw,desc,task,p

    def test_complete_static_supported_state(self):
        self.assertTrue(evaluate(*self.fixture())['passed'])

    def test_incomplete_run_is_not_static_success(self):
        raw,d,t,p=self.fixture()
        for name in ['times','qpos','qvel','states','warnings']:raw[name]=raw[name][:-1]
        raw['contacts']=raw['contacts'][:-1];raw['frames']=raw['frames'][:-1]
        self.assertFalse(evaluate(raw,d,t,p)['passed'])

    def test_initial_interpenetration_rejected(self):
        raw,d,t,p=self.fixture();raw['initial_contacts']=raw['contacts'][:1].copy();raw['initial_contacts'][0,4]=-.002
        self.assertFalse(evaluate(raw,d,t,p)['checks']['initial_contact'])

    def test_weight_force_uses_complete_frame_and_target_sign(self):
        raw,d,t,p=self.fixture();raw['contacts'][:,1:3]=[1,2]
        self.assertFalse(evaluate(raw,d,t,p)['passed'])

    def test_tipping_rejected(self):
        raw,d,t,p=self.fixture();raw['qpos'][:,3:7]=[np.cos(np.pi/12),np.sin(np.pi/12),0.,0.]
        self.assertFalse(evaluate(raw,d,t,p)['checks']['orientation'])

    def test_other_object_cannot_replace_support(self):
        raw,d,t,p=self.fixture();raw['contacts'][:,3]=3
        self.assertFalse(evaluate(raw,d,t,p)['checks']['support_contact_every_tail_step'])
