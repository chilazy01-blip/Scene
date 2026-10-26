import unittest
import numpy as np
from .geometry import translation_region,world_ray_height


class TranslationRegionTests(unittest.TestCase):
    def test_both_footprints_covered(self):
        a=np.array([.04,-.13]);b=np.array([.14,-.13]);extent=np.array([.0445,.17]);roi,n=translation_region(a,b,extent,.005,.02)
        for x in [a,b]:
            self.assertTrue(np.all(roi[0]<=x-extent/2-.02+1e-12))
            self.assertTrue(np.all(roi[1]>=x+extent/2+.02-1e-12))
        np.testing.assert_allclose(n*.005,roi[1]-roi[0])

    def test_translation_equivariance_on_grid(self):
        first,_=translation_region(np.array([0.,0.]),np.array([.1,0.]),np.array([.0445,.17]),.005,.02)
        second,_=translation_region(np.array([-.1,.2]),np.array([0.,.2]),np.array([.0445,.17]),.005,.02)
        np.testing.assert_allclose(second,first+[-.1,.2],atol=1e-12)

    def test_negative_translation(self):
        a,n=translation_region([.1,0.],[0.,0.],[.0445,.17],.005,.02)
        b,m=translation_region([0.,0.],[.1,0.],[.0445,.17],.005,.02)
        np.testing.assert_array_equal(a,b);np.testing.assert_array_equal(n,m)


class WorldRayTests(unittest.TestCase):
    def fixture(self):
        pose=np.eye(4);pose[:3,3]=[2.4,3.56,0.]
        return pose,np.array([[-.0025,0.,0.],[.0025,0.,0.]]),np.array([[.0025,.01,.1],[.0025,.01,.2]])

    def test_world_roundoff_selects_actual_side_of_seam(self):
        pose,c,s=self.fixture();origin=np.array([np.nextafter(2.4,-np.inf),3.56,1.])
        self.assertAlmostEqual(world_ray_height(origin,1.,pose,c,s),.1,places=12)

    def test_column_order_does_not_change_first_hit(self):
        pose,c,s=self.fixture();origin=np.array([2.4025,3.56,1.])
        self.assertAlmostEqual(world_ray_height(origin,1.,pose,c[::-1],s[::-1]),.2,places=12)

    def test_miss_remains_missing(self):
        pose,c,s=self.fixture()
        self.assertTrue(np.isnan(world_ray_height([5.,3.56,1.],1.,pose,c,s)))
