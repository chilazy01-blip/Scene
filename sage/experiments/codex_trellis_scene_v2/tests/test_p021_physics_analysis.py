"""Reject plausible horizontal traces that violate independent physics gates."""
from copy import deepcopy
import unittest

import numpy as np

from sage.experiments.codex_trellis_scene_v2.p021_physics_analysis import analyze_saved_world, rolling_force_support


class SavedWorldAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.thresholds = {'residual_window_s':.5,'stopped_speed_m_s':.01,
            'minimum_stopped_duration_s':.2,'analytic_max_tilt_degrees':5.,
            'analytic_max_lateral_m':.01,'analytic_max_plane_gap_m':.001,
            'analytic_max_nonforward_energy_fraction':.05,
            'settled_vertical_speed_m_s':.01,'settled_angular_speed_rad_s':.02,
            'distance_absolute_m':.005,'distance_relative':.1,'time_absolute_s':.04,
            'time_relative':.1,'floor_penetration_m':.002,'floor_suspension_m':.002,
            'residual_linear_rms_m_s':.01,'residual_angular_rms_rad_s':.02}
        self.spec={'simulation':{'dt':.002,'action_s':2.,'initial_velocity_m_s':[1.5,0,0]},
            'method':'A_support_priority','floor_mu':.3,'room':{'width':6.,'length':5.,'height':2.8}}
        self.binding={'objects':{'asset':{'compiled':{'mass_kg':1.,
            'diagonal_inertia_kg_m2':[1/6]*3,'inertial_quaternion_wxyz':[1,0,0,0]}}},
            'floor':{'support_z_m':0.}}
        t=np.arange(1001)*.002
        speed=np.maximum(0,1.5-2.943*t)
        stop=1.5/2.943
        x=1.5*np.minimum(t,stop)-.5*2.943*np.minimum(t,stop)**2
        n=len(t)+1
        matrix=np.tile(np.eye(4),(n,1,1,1))
        matrix[:,0,:3,3]=[2.,2.,.5]
        matrix[1:,0,0,3]+=x
        linear=np.zeros((n,1,3));linear[1:,0,0]=speed
        bounds=np.zeros((n,1,2,3))
        bounds[:,0,0,:]=matrix[:,0,:3,3]-.5
        bounds[:,0,1,:]=matrix[:,0,:3,3]+.5
        self.dense={'object_ids':np.array(['asset']),'action_time_s':np.r_[-1.,t],
            'matrix_world_z_up':matrix,'linear_velocity_m_s':linear,
            'angular_velocity_rad_s':np.zeros((n,1,3)), 'world_bounds_z_up':bounds,
            'floor_contact_count':np.ones((n,1),dtype=int)}

    def result(self):
        return analyze_saved_world(self.dense,self.binding,self.spec,self.thresholds)['asset']

    def test_ideal_coulomb_saved_world_passes(self):
        self.assertTrue(self.result()['passed'])

    def test_body_local_axis_choice_is_not_physical_tilt(self):
        self.dense['matrix_world_z_up'][:,0,:3,:3]=[[1,0,0],[0,0,-1],[0,1,0]]
        result=self.result()
        self.assertEqual(result['max_action_tilt_degrees'],0.)
        self.assertTrue(result['passed'])

    def test_small_initial_energy_fraction_cannot_hide_late_rocking(self):
        # 0.0004 J is only 0.036% of initial KE, but exceeds current
        # translation energy just before stopping. It invalidates the reference.
        self.dense['angular_velocity_rad_s'][252:255,0,1]=.07
        result = self.result()
        self.assertTrue(result['gates']['bounded_nonforward_energy'])
        self.assertFalse(result['gates']['forward_energy_dominates_while_moving'])
        self.assertEqual(result['analytic_status'], 'not_applicable')
        self.assertIsNone(result['gates']['analytic_stopping_time'])
        self.assertTrue(result['dynamic_health_passed'])
        self.assertFalse(result['benchmark_passed'])

    def test_airborne_correct_horizontal_formula_is_not_accepted(self):
        self.dense['floor_contact_count'][10:25,0]=0
        self.dense['world_bounds_z_up'][10:25,0,:,2]+=.01
        self.assertFalse(self.result()['gates']['analytic_applicable'])

    def test_spinning_correct_horizontal_formula_is_not_accepted(self):
        self.dense['angular_velocity_rad_s'][10:25,0,2]=2.
        self.assertFalse(self.result()['gates']['analytic_applicable'])

    def test_unsettled_impulse_is_not_accepted(self):
        self.dense['linear_velocity_m_s'][0,0,2]=-.1
        self.assertFalse(self.result()['gates']['pre_impulse_settled'])

    def test_wrong_world_floor_is_not_accepted(self):
        self.dense['world_bounds_z_up'][:,0,:,2]-=.01
        self.assertFalse(self.result()['gates']['floor_penetration'])

    def test_missing_dense_step_rejected(self):
        self.dense['action_time_s'][20]+=.001
        with self.assertRaisesRegex(ValueError,'every physics timestep'):
            self.result()

    def test_changed_object_identity_rejected(self):
        self.dense['object_ids']=np.array(['other'])
        with self.assertRaisesRegex(ValueError,'object IDs'):
            self.result()

    def test_fixed_bins_do_not_hide_rolling_force_gap(self):
        result=rolling_force_support([.001,.199],.2,.1)
        self.assertFalse(result['passed'])
        self.assertAlmostEqual(result['maximum_force_observation_gap_s'],.198)

    def test_dense_positive_force_observations_cover_rolling_windows(self):
        self.assertTrue(rolling_force_support([0,.05,.1,.15,.2],.2,.1)['passed'])

    def test_empty_force_observations_do_not_pass(self):
        self.assertFalse(rolling_force_support([],.2,.1)['passed'])


if __name__=='__main__':
    unittest.main()
