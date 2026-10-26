import unittest
from copy import deepcopy

from sage.experiments.codex_trellis_scene_v2.asset_usage import bind_asset_usage, asset_usage_violations
from sage.experiments.codex_trellis_scene_v2.orientation import solve_facing_yaw


class AssetUsageTests(unittest.TestCase):
    def setUp(self):
        self.entry = {"asset_id":"arbitrary_picture", "usage_constraints":["wall_mounted","front_only","back_against_wall"], "asset_canonical_front":{"axis":"+y","confidence":.9}}

    def test_all_walls_receive_executable_front_constraint(self):
        for wall, expected in (("west",270),("east",90),("north",180),("south",0)):
            with self.subTest(wall=wall):
                obj={"id":"picture", "asset_id":"arbitrary_picture", "placement_type":"wall", "preferred_wall":wall, "yaw":(expected+180)%360}
                bind_asset_usage({"objects":[obj]}, {"assets":[self.entry]})
                self.assertTrue(asset_usage_violations(obj))
                self.assertEqual(solve_facing_yaw(obj),expected)
                obj['yaw']=solve_facing_yaw(obj)
                self.assertEqual(asset_usage_violations(obj),[])
                obj.pop('facing_constraint')
                self.assertTrue(asset_usage_violations(obj))

    def test_no_fallback_front_certificate_for_restricted_asset(self):
        obj={"id":"picture", "usage_constraints":["back_against_wall"], "preferred_wall":"west", "facing_constraint":{"mode":"into_room","wall":"west"}, "yaw":90}
        self.assertTrue(asset_usage_violations(obj))

    def test_conflicting_user_constraint_is_not_silently_rewritten(self):
        obj={"id":"picture", "asset_id":"arbitrary_picture", "preferred_wall":"west", "facing_constraint":{"mode":"into_room","wall":"east"}}
        with self.assertRaises(ValueError):
            bind_asset_usage({"objects":[obj]}, {"assets":[self.entry]})

    def test_manifest_and_unrestricted_assets_are_unchanged(self):
        manifest={"assets":[self.entry]}; before=deepcopy(manifest)
        obj={"id":"plant", "asset_id":"unrestricted"}; initial=deepcopy(obj)
        bind_asset_usage({"objects":[obj]},manifest)
        self.assertEqual(obj,initial); self.assertEqual(manifest,before)

    def test_front_review_evidence_does_not_break_typed_front_contract(self):
        self.entry['asset_canonical_front']['review_evidence'] = {'path': 'review.json'}
        obj={'id':'picture','asset_id':'arbitrary_picture','preferred_wall':'west'}
        result=bind_asset_usage({'objects':[obj]}, {'assets':[self.entry]})
        self.assertEqual(set(obj['asset_canonical_front']), {'axis','confidence'})
        self.assertEqual(result['results'][0]['canonical_front_evidence']['review_evidence'], {'path':'review.json'})


if __name__=='__main__': unittest.main()
