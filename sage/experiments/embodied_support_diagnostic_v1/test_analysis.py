import unittest
import numpy as np
from .analysis import support_margin, first_run, rotations, coupled_envelope


class DiagnosticsTests(unittest.TestCase):
    def test_polygon_known_inside_and_outside(self):
        points = np.array([[-1,-1],[1,-1],[1,1],[-1,1]])
        self.assertAlmostEqual(support_margin(points, [0,0])[0], 1.)
        self.assertAlmostEqual(support_margin(points, [2,0])[0], -1.)
        self.assertAlmostEqual(support_margin(points, [0,0])[1], 4.)

    def test_degenerate_line(self):
        self.assertAlmostEqual(support_margin([[0,0],[1,0],[.5,0]], [.5,.2])[0], -.2)
        self.assertAlmostEqual(support_margin([[0,0],[1,0]], [2,0])[0], -1.)

    def test_duplicate_and_empty(self):
        self.assertTrue(np.isnan(support_margin([], [0,0])[0]))
        self.assertEqual(support_margin([[0,0],[0,0]], [0,0]), (0., 0., 1))

    def test_nonfinite_refused(self):
        with self.assertRaises(ValueError):support_margin([[np.nan,0]], [0,0])

    def test_sustained_event_start(self):
        self.assertEqual(first_run([False,True,False,True,True], .001, .002), 3)
        self.assertIsNone(first_run([True,False,True], .001, .002))

    def test_rotation_known(self):
        r = rotations([[2,0,0,0], [np.sqrt(.5),0,np.sqrt(.5),0]])
        np.testing.assert_allclose(r[0], np.eye(3), atol=1e-15)
        np.testing.assert_allclose(r[1] @ [0,0,1], [1,0,0], atol=1e-15)
        with self.assertRaises(ValueError):rotations([[0,0,0,0]])

    def test_envelope_preserves_holes(self):
        xy=np.array([[-1,0],[0,0],[1,0]])
        result,gap=coupled_envelope(xy,np.array([0,np.nan,0]),np.zeros(3),[0,0],[.001])
        self.assertEqual(result['samples'],2)
        self.assertTrue(np.isnan(gap[1]))

    def test_envelope_accounts_for_object_underside(self):
        xy=np.array([[-1,0],[0,0],[1,0]])
        result,gap=coupled_envelope(xy,np.array([0,0,0]),np.array([.002,0,.003]),[0,0],[.0005])
        self.assertEqual(result['bands'][0]['samples'],1)
        np.testing.assert_allclose(gap,[.002,0,.003])
