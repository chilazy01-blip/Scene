import copy
import unittest
from .contracts import observe
from .experience import retrieve, promotion_gate

class ContractsTest(unittest.TestCase):
    def test_object_frame_is_independent_of_robot_root(self):
        s=dict(object_rotation=[[1,0,0],[0,0,-1],[0,1,0]],stage='carry',desk_supported=False,safe=True,
            hand_contact=False,tick=12,time_after_s=.26,up=1.,forces={},object_m=[0,0,1],object_local_m=[0,0,1])
        v=observe(s,dict(object_id='bottle',orientation_axis=[0,0,1]))
        self.assertEqual(v['robot_root_up_cosine'],1)
        self.assertEqual(v['object_orientation_cosine'],0)
        self.assertIn('airborne_grasp_contact_absent',v['diagnostic_breaches'])
        s['stage']='place';s['desk_supported']=True
        self.assertFalse(observe(s,dict(object_id='bottle'))['diagnostic_breaches'])

    def test_partial_or_hypothesis_cannot_be_complete_skill(self):
        scope=dict(robot='G1',body_control='SONIC29',hand_control='original native14handPD',loaded_reference_ratio=.65,solver_schedule={},object_asset='bottle')
        record=dict(id='partial',applicability=scope,status='untested_hypothesis',evidence=[dict(case_id='S02',physical_model={'sha256':'a'},task_passed=False)])
        query=dict(scope,case_id='S02',model_sha256='a')
        result=retrieve(dict(records=[record]),query,'complete_skill')
        self.assertEqual(result['matches'],[])
        self.assertIn('not_independently_complete_skill',result['rejected'][0]['reasons'])
        query['robot']='other'
        self.assertIn('scope:robot',retrieve(dict(records=[record]),query)['rejected'][0]['reasons'])

    def test_empty_or_unverified_promotion_is_rejected(self):
        self.assertFalse(promotion_gate([],[])['eligible'])
        self.assertFalse(promotion_gate([],['S02','S03'])['eligible'])
        self.assertFalse(promotion_gate([dict(case_id='S02',independently_qualified=False)],['S02'])['eligible'])

if __name__=='__main__':unittest.main()
