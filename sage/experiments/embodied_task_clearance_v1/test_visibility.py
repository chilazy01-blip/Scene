import unittest
import numpy as np
from .visibility import assess,camera_pose


class VisibilityTests(unittest.TestCase):
    limits=dict(width=10,height=10,minimum_visible_target_pixels=20,minimum_unoccluded_target_pixels=20,minimum_visible_fraction=.5)
    def test_empty_target_fails(self):self.assertFalse(assess(np.zeros((10,10),bool),np.zeros((10,10),bool),self.limits)['passed'])
    def test_large_occluded_target_fails(self):
        visible=np.zeros((10,10),bool);visible[:3]=True
        self.assertFalse(assess(visible,np.ones((10,10),bool),self.limits)['passed'])
    def test_visible_target_passes(self):self.assertTrue(assess(np.ones((10,10),bool),np.ones((10,10),bool),self.limits)['passed'])
    def test_tiny_target_fails(self):
        mask=np.zeros((10,10),bool);mask[0]=True;self.assertFalse(assess(mask,mask,self.limits)['passed'])
    def test_inconsistent_projection_rejected(self):
        with self.assertRaises(ValueError):assess(np.ones((10,10),bool),np.zeros((10,10),bool),self.limits)
    def test_camera_looks_at_target_from_inside(self):
        from scipy.spatial.transform import Rotation
        goal=np.eye(4);goal[:3,3]=[3.6,3.,.524]
        pos,quat=camera_pose(goal,dict(width=4.8,length=4.,height=2.7),dict(horizontal_distance_m=1.8,height_above_target_m=1.4,wall_margin_m=.25,look_at_z_offset_m=.03))
        self.assertTrue(np.all(pos>[.25,.25,.25]) and np.all(pos<[4.55,3.75,2.45]))
        direction=goal[:3,3]+[0,0,.03]-pos;direction/=np.linalg.norm(direction)
        self.assertTrue(np.allclose(-Rotation.from_quat(quat[[1,2,3,0]]).as_matrix()[:,2],direction))
