import unittest
import numpy as np
from .planner import select, orientations, corners, generation_inputs
from sage.experiments.embodied_scene_quality_v1.contracts import Rejected


def asset(name,category,dims):
    return dict(asset_id=name,category=category,dimensions=dict(zip(('width','length','height'),dims)))


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.policy=dict(surface_edge_inset_m=.03,placement_margin_m=.005,xy_offset_envelope_m=.006,
                         rotation_envelope_deg=2.,allowed_yaw_deg=[0,90])
        self.lib=dict(library_id='synthetic',assets=[asset('arbitrary_object','single_book',[.04,.17,.24]),
            asset('arbitrary_support','desk',[1.4,.72,.75])])
        self.request=dict(id='arbitrary_request',target_pool=['arbitrary_object'],task='place_on_surface',
                          posture='broad_face_down',support_category='desk')

    def test_thinnest_axis_down(self):
        for dims in ([.04,.17,.24],[.2,.03,.1],[.2,.1,.02]):
            for _,rot in orientations(dims,'broad_face_down',[0,90]):
                self.assertAlmostEqual(np.ptp(corners(dims)@rot.T,axis=0)[2],min(dims))
                self.assertAlmostEqual(np.linalg.det(rot),1.)

    def test_not_an_asset_id_whitelist(self):
        selected=select(self.lib,self.request,self.policy)
        self.assertTrue(selected['selected']);self.assertEqual(selected['physical_qualification'],'unknown')

    def test_insufficient_cavity_rejected(self):
        self.request.update(task='place_in_container')
        result=select(self.lib,self.request,self.policy,dict(verified=True,inner_bounds_local_m=[[-.1,-.11,-.16],[.1,.11,.115]]))
        self.assertIsNone(result['selected']);self.assertEqual(len(result['candidates']),2)

    def test_margin_is_required(self):
        self.lib['assets'][1]['dimensions'].update(width=.30,length=.235)
        self.assertIsNone(select(self.lib,self.request,self.policy)['selected'])

    def test_missing_pool_rejected(self):
        self.request['target_pool'].append('missing')
        with self.assertRaises(Rejected):select(self.lib,self.request,self.policy)

    def test_selection_independent_of_input_order(self):
        self.lib['assets'].append(asset('larger','single_book',[.04,.19,.25]));self.request['target_pool'].append('larger')
        original=select(self.lib,self.request,self.policy)
        self.lib['assets'].reverse()
        self.assertEqual(original,select(self.lib,self.request,self.policy))

    def test_selected_asset_constrains_public_input(self):
        self.lib['assets'].append(asset('not_selected','single_book',[.04,.3,.4]))
        result=select(self.lib,self.request,self.policy)
        subset,furnishing,prompt=generation_inputs(self.lib,self.request,result)
        self.assertEqual([a['asset_id'] for a in subset['assets'] if a['category']=='single_book'],['arbitrary_object'])
        self.assertEqual(furnishing['attachments'][0]['parent_id'],'desk')
        self.assertIn('flat',prompt)


if __name__=='__main__':unittest.main()
