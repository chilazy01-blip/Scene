import unittest
from copy import deepcopy
from ..furnishing_groups import ground_groups, place_groups, evaluate_groups, allowed_window_treatment, rotate
from ..policies import _obj
from ..scene_graph import build_typed_scene_graph


class FurnishingGroupsTests(unittest.TestCase):
    def test_triangle_crossing_box_is_detected_without_inside_vertices(self):
        import numpy as np
        from ..furnishing_geometry import triangles_in_box
        triangle=np.array([[[-2.,-2.,0.],[2.,-2.,0.],[0.,2.,0.]]])
        self.assertEqual(triangles_in_box(triangle,np.array([-.1,-.1,-.1]),np.array([.1,.1,.1])),1)
        self.assertEqual(triangles_in_box(triangle+np.array([0,0,2.]),np.array([-.1,-.1,-.1]),np.array([.1,.1,.1])),0)

    def test_real_architecture_stage_envelope(self):
        from ..brief import build_baseline_brief
        from ..architecture import plan_architecture
        brief=build_baseline_brief('A warm bedroom with curtain panels.')
        architecture=plan_architecture(brief)
        ground_groups(brief,architecture,{'window_treatments':{'mode':'paired_open'},'wall_pbr':True})
        self.assertEqual(sum('window_treatment' in o for o in brief['objects']),3*len(brief['architecture']['windows']))
        self.assertTrue(architecture['architecture']['wall_finish']['default']['embed_pbr_maps'])
        graph=build_typed_scene_graph(brief,architecture)
        nodes={n['id']:n for n in graph['nodes']}
        for obj in brief['objects']:
            if obj.get('window_treatment'):
                self.assertEqual(nodes[obj['id']]['parent_id'],obj['window_treatment']['window_id'])

    def brief(self, yaw=0, width=1.8):
        bed=_obj('bed','bed');bed['dimensions']['width']=width
        bed['initial_pose']={'x':5.,'y':5.,'yaw':yaw}
        rug=_obj('rug','area_rug')
        return {'room':{'width':10.,'length':10.,'height':3.},'objects':[bed,rug],
                'relations':[],'object_budget':{'hard_runtime_limit':40},'architecture':{
                    'windows':[{'id':'window_one','wall':'west','center':2.6,'width':1.4,'height':1.15,'sill_height':1.05}]}}

    def test_whole_bed_coverage_survives_size_yaw_and_parent_translation(self):
        for yaw in (0,37,90,180,270):
            for width in (1.2,1.8,2.1):
                with self.subTest(yaw=yaw,width=width):
                    brief=self.brief(yaw,width)
                    config={'rugs':[{'anchor_id':'bed','rug_id':'rug','covered_ids':['bed'],'margins_m':[.2,.5,.1]}]}
                    ground_groups(brief,brief['architecture'],config)
                    for obj in brief['objects']:obj.update(obj.get('initial_pose',{}))
                    place_groups(brief)
                    self.assertEqual(evaluate_groups(brief),[])
                    brief['objects'][0]['x']+=.7;brief['objects'][0]['y']-=.3
                    place_groups(brief)
                    self.assertEqual(evaluate_groups(brief),[])
                    self.assertAlmostEqual(brief['objects'][0]['z'],.02)

    def test_repaired_group_cannot_silently_stretch_resolved_rug(self):
        brief=self.brief();ground_groups(brief,brief['architecture'],{'rugs':[{'anchor_id':'bed','rug_id':'rug','covered_ids':['bed']}]})
        for obj in brief['objects']:obj.update(obj.get('initial_pose',{}))
        brief['objects'][0]['dimensions']['width']=4.
        before=deepcopy(brief['objects'][1]['dimensions']);place_groups(brief)
        self.assertTrue(evaluate_groups(brief));self.assertEqual(before,brief['objects'][1]['dimensions'])

    def test_treatments_follow_each_actual_opening_and_have_specific_exemption(self):
        for wall in ('north','south','east','west'):
            brief=self.brief();windows=brief['architecture']['windows'];windows[0]['wall']=wall
            windows.append(dict(windows[0],id='window_two',center=6.,width=2.))
            ground_groups(brief,brief['architecture'],{'window_treatments':{'mode':'paired_open'}})
            place_groups(brief)
            curtains=[o for o in brief['objects'] if 'window_treatment' in o]
            self.assertEqual(len(curtains),6)
            for window in windows:
                members=[o for o in curtains if o['window_treatment']['window_id']==window['id']]
                self.assertEqual({o['window_treatment']['role'] for o in members},{'left','right','rod'})
                rod=next(o for o in members if o['category']=='curtain_rod')
                self.assertTrue(allowed_window_treatment(rod,window))
                self.assertFalse(allowed_window_treatment(dict(rod,category='wardrobe'),window))
                self.assertFalse(allowed_window_treatment(rod,dict(window,id='different')))

    def test_surface_offsets_rotate_and_include_parent_elevation(self):
        brief=self.brief();desk=_obj('desk','desk');desk.update(x=4.,y=4.,z=.02,yaw=37.)
        brief['objects'].append(desk)
        ground_groups(brief,brief['architecture'],{'attachments':[{'id':'mug','category':'mug','parent_id':'desk','mode':'surface','offset_fraction':[.25,-.2]}]})
        place_groups(brief);mug=brief['objects'][-1];dx,dy=rotate(.35,-.144,37)
        self.assertAlmostEqual(mug['x'],4+dx);self.assertAlmostEqual(mug['y'],4+dy)
        self.assertAlmostEqual(mug['z'],.77)
