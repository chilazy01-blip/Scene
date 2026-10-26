import unittest
import numpy as np
from .contract import action_blocks,check_times,statistics
from .dataset import EpisodeDataset

class ContractTests(unittest.TestCase):
    def data(self):
        q=np.arange(700,dtype=float).reshape(100,7)/1000;v=q+2;u=np.zeros((100,9));u[:,7]=np.arange(100)/100*.04;u[:,8]=-u[:,7]
        return q,v,u
    def test_every_substep_and_velocity_survives_chunking(self):
        q,v,u=self.data();a=action_blocks(q,v,u,[7,8]);self.assertEqual(a.shape,(2,50,15))
        np.testing.assert_array_equal(a.reshape(100,15)[:,:7],q);np.testing.assert_array_equal(a.reshape(100,15)[:,7:14],v)
        np.testing.assert_array_equal(a.reshape(100,15)[:,14],u[:,7])
    def test_incomplete_action_block_rejected(self):
        q,v,u=self.data()
        with self.assertRaisesRegex(ValueError,'substep_count'):action_blocks(q[:-1],v[:-1],u[:-1],[7,8])
    def test_missing_velocity_rejected(self):
        q,v,u=self.data()
        with self.assertRaisesRegex(ValueError,'position_velocity_shape'):action_blocks(q,v[:,:6],u,[7,8])
    def test_gripper_sign_rejected(self):
        q,v,u=self.data();u[:,8]=u[:,7]
        with self.assertRaisesRegex(ValueError,'gripper_sign'):action_blocks(q,v,u,[7,8])
    def test_time_alignment_and_shift(self):
        steps=np.arange(3)*50;check_times(steps*.001,steps)
        with self.assertRaisesRegex(ValueError,'observation_times'):check_times(steps*.001+.001,steps)
    def test_missing_frame_step_rejected(self):
        with self.assertRaisesRegex(ValueError,'frame_steps'):check_times(np.array([0.,.1]),np.array([0,100]))
    def test_bright_uint8_variance_does_not_overflow(self):
        rgb=np.array([[[250,254,248],[254,250,252]]],dtype=np.uint8);mean,std=statistics(rgb)
        np.testing.assert_array_equal(mean,[252,252,250]);np.testing.assert_array_equal(std,[2,2,2])
    def test_reader_does_not_wrap_invalid_indices(self):
        dataset=object.__new__(EpisodeDataset)
        for index in [-1,350,1.5]:
            with self.assertRaises(IndexError):dataset[index]
