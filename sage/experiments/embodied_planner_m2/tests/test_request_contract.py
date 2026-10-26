import unittest
from copy import deepcopy
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.architecture import plan_architecture
from sage.experiments.codex_trellis_scene_v2.furnishing_groups import ground_groups
from sage.experiments.codex_trellis_scene_v2.dimensions import resolve_dimension_adaptation

PROMPT='Create a modern study with a wooden desk, an office chair, a bookcase and a floor lamp.'
CONFIG={'attachments':[{'id':'novel_item','category':'single_book','parent_id':'desk','mode':'surface'}]}
class RequestContracts(unittest.TestCase):
 def build(self,prompt=PROMPT,config=None):
  brief=build_baseline_brief(prompt,room_type_override='study');arch=plan_architecture(brief)
  ground_groups(brief,arch,deepcopy(CONFIG if config is None else config));return brief
 def test_unspecified_attachment_dimension_is_source_resolved_prior(self):
  brief=self.build();obj=next(o for o in brief['objects'] if o['id']=='novel_item')
  self.assertEqual(obj['dimension_policy']['request_origin'],'inferred_category_prior')
  self.assertEqual(obj['dimension_grounding'],'inferred_category_prior')
 def test_explicit_dimensions_stay_strict(self):
  config=deepcopy(CONFIG);config['attachments'][0]['dimensions_m']=[.031,.17,.25]
  obj=next(o for o in self.build(config=config)['objects'] if o['id']=='novel_item')
  self.assertNotIn('request_origin',obj['dimension_policy'])
  self.assertEqual(obj['dimensions'],dict(width=.031,length=.17,height=.25))
 def test_attachment_completes_explicit_list_without_optional_proposals(self):
  brief=self.build();self.assertNotIn('cabinet',[o['category'] for o in brief['objects']])
  self.assertEqual(len(brief['objects']),5)
  self.assertTrue(brief['furnishing_budget_resolution']['before_asset_selection_and_layout'])
 def test_explicit_cabinet_not_dropped(self):
  brief=self.build(PROMPT+' Include a cabinet.')
  self.assertIn('cabinet',[o['category'] for o in brief['objects']])
 def test_relationship_target_not_dropped(self):
  brief=build_baseline_brief(PROMPT,room_type_override='study');arch=plan_architecture(brief)
  brief['relations'].append(['desk','near','cabinet']);ground_groups(brief,arch,deepcopy(CONFIG))
  self.assertIn('cabinet',[o['category'] for o in brief['objects']])
 def test_existing_explicit_object_size_not_reclassified(self):
  brief=build_baseline_brief(PROMPT+' Include one individual single book.',room_type_override='study')
  obj=next(o for o in brief['objects'] if o['category']=='single_book')
  obj['dimension_policy'].pop('request_origin',None);obj['dimension_grounding']='explicit_external_size'
  arch=plan_architecture(brief);cfg=deepcopy(CONFIG);cfg['attachments'][0].update(id=obj['id'],use_existing=True)
  ground_groups(brief,arch,cfg)
  self.assertNotIn('request_origin',obj['dimension_policy'])
