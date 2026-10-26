import unittest
import numpy as np
import trimesh
from .geometry import merge_intervals,deepest_overlap,solid_intervals,box_intervals,compare,pack,unpack,closed_components


class GeometryTests(unittest.TestCase):
    def test_union_preserves_gap(self):self.assertEqual(merge_intervals([[0,1],[.5,1.5],[2,3]]),[[0.,1.5],[2.,3.]])
    def test_touch_is_not_penetration(self):self.assertEqual(deepest_overlap([[0,1]],[[1,2]])[0],0)
    def test_intersecting_interval(self):self.assertAlmostEqual(deepest_overlap([[0,1]],[[.75,2]])[0],.25)
    def test_disconnected_source_not_filled(self):
        low=trimesh.creation.box([1,1,.1]);high=low.copy();high.apply_translation([0,0,1])
        intervals,known=solid_intervals([low,high],np.array([[0.,0.]]),2.,1e-7)
        self.assertTrue(known[0]);self.assertEqual(len(intervals[0]),2)
        self.assertEqual(deepest_overlap(intervals[0],[[.3,.4]])[0],0)
    def test_rotated_proxy_bounds(self):
        rot=np.array([[0.,-1,0],[1,0,0],[0,0,1]])
        value=box_intervals(np.zeros((1,3)),np.array([[.1,.2,.3]]),[rot],np.array([[.15,0],[0,.15]]),1e-7)
        self.assertEqual(value,[[[-.3,.3]],[]])
    def test_proxy_expansion_does_not_implicate_source(self):
        value,_=compare([[[0,1]]],[[[0,1.1]]],[[[1.05,1.2]]],[True],[True],True,.001)
        self.assertEqual(value['classification'],'proxy_only_on_sampled_rays')
    def test_unknown_never_proves_clearance(self):
        value,_=compare([[]],[[[0,1]]],[[[.5,.6]]],[False],[True],False,.001)
        self.assertEqual(value['classification'],'unknown_or_no_witness')
    def test_interval_storage(self):
        values=[[],[[0.,1.],[2.,3.]]];p,c=pack(values,128);self.assertEqual(unpack(p,c),values)
    def test_source_hole_is_never_filled(self):
        box=trimesh.creation.box();opened=trimesh.Trimesh(box.vertices,box.faces[:-1],process=False)
        closed,topology=closed_components(opened,9,128)
        self.assertEqual(len(closed),0);self.assertFalse(topology['complete']);self.assertEqual(len(opened.faces),11)
