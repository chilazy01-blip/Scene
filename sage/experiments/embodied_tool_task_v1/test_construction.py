import unittest
import numpy as np
from .construction import clearance_gap
from .entry import saved_contact_decision


class ToolConstructionTests(unittest.TestCase):
    support=np.array([[[-1,-1,0],[1,1,.5]]])
    def test_required_vertical_gap(self):
        gap,_=clearance_gap({'hand':[[-.1,-.1,.48],[.1,.1,.6]]},self.support,.002,.001)
        self.assertAlmostEqual(gap,.022)
    def test_no_xy_overlap_does_not_raise_height(self):
        gap,_=clearance_gap({'hand':[[2,2,0],[3,3,1]]},self.support,.002,.001);self.assertEqual(gap,.001)
    def test_open_finger_included(self):
        closed={'closed':[[-.1,-.1,.55],[.1,.1,.6]]};opened=dict(closed,opened=[[-.1,-.1,.47],[.1,.1,.6]])
        self.assertGreater(clearance_gap(opened,self.support,.002,.001)[0],.03)
        self.assertEqual(clearance_gap(closed,self.support,.002,.001)[0],.001)
    def test_multiple_support_layers_use_top(self):
        support=np.concatenate([self.support,self.support+[0,0,1]])
        self.assertAlmostEqual(clearance_gap({'tool':[[-.1,-.1,.48],[.1,.1,.6]]},support,.002,.001)[0],1.022)
    def test_xy_margin_is_conservative(self):
        gap,_=clearance_gap({'tool':[[1.001,-.1,.48],[1.1,.1,.6]]},self.support,.002,.001);self.assertAlmostEqual(gap,.022)
    def test_saved_collision_rejected(self):self.assertFalse(saved_contact_decision(dict(violations=[dict(penetration_m=.039)]),.001)['passed'])
    def test_empty_saved_contacts_are_not_full_qualification(self):
        row=saved_contact_decision(dict(violations=[]),.001);self.assertTrue(row['passed']);self.assertEqual(row['scope'],'saved native contact state only')
