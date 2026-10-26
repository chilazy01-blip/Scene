import unittest
from .test_planner import asset
from .planner import generation_inputs
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.furnishing_groups import ground_groups


class RoleTests(unittest.TestCase):
    def test_roles_resolve_without_duplicate_target(self):
        for category in ('desk','side_table'):
            request=dict(id='role_test',room_type='study',support_category=category)
            library=dict(library_id='roles',assets=[asset('book','single_book',[.04,.17,.24])])
            _,config,prompt=generation_inputs(library,request,dict(selected=dict(asset_id='book')))
            brief=build_baseline_brief(prompt,'study');ground_groups(brief,{},config)
            ids={o['id'] for o in brief['objects']};books=[o for o in brief['objects'] if o['category']=='single_book']
            self.assertEqual(len(books),1)
            self.assertIn(books[0]['support_id'],ids)
            support=next(o for o in brief['objects'] if o['id']==books[0]['support_id'])
            self.assertEqual(support['category'],category)


if __name__=='__main__':unittest.main()
