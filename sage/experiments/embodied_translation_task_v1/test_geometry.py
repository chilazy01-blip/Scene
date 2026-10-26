import unittest
import numpy as np
from .geometry import translation_region


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
