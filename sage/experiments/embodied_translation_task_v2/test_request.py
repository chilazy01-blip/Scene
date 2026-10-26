import unittest,tempfile,json
from pathlib import Path
from sage.experiments.codex_trellis_scene_v2.brief import build_baseline_brief
from sage.experiments.codex_trellis_scene_v2.assets import AssetRegistry
from .request import separate


class RequestScopeTests(unittest.TestCase):
    def fixture(self):
        return 'Create a study with a desk, a bookcase, a floor lamp and one individual single book.',dict(kind='orientation_preserving_translation',translation_frame='support_local',goal_offset_xy_m=[.1,0.],preserve_source_orientation=True,target_asset_id='book',support_category='desk')

    def test_task_quantity_does_not_change_scene_dimensions(self):
        scene,spec=self.fixture();first=separate(scene,spec);spec['goal_offset_xy_m']=[.2,0.];second=separate(scene,spec)
        self.assertEqual(first['task_spec']['goal_offset_xy_m'],[.1,0.])
        self.assertNotEqual(first['task_spec'],second['task_spec'])
        self.assertEqual(build_baseline_brief(first['scene_description'],'study'),build_baseline_brief(second['scene_description'],'study'))

    def test_explicit_scene_dimensions_are_preserved_and_strict(self):
        scene,spec=self.fixture();scene+=' The single book is 3 cm wide.'
        record=separate(scene,spec);self.assertEqual(record['scene_description'],scene)
        book=next(o for o in build_baseline_brief(scene,'study')['objects'] if o['category']=='single_book')
        self.assertNotEqual(book['dimension_policy'].get('request_origin'),'inferred_category_prior')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'stub.glb').write_bytes(b'path-existence fixture; no geometry read')
            (root/'manifest.json').write_text(json.dumps(dict(assets=[dict(asset_id='book',category='single_book',glb_path=str(root/'stub.glb'),dimensions=dict(width=.0444979,length=.169654,height=.24))])))
            rejected=[];match=AssetRegistry(root/'manifest.json').find('single_book',[],target_dimensions=book['requested_dimensions'],dimension_policy=book['dimension_policy'],rejections=rejected)
            self.assertIsNone(match);self.assertEqual(len(rejected),1)

    def test_legacy_motion_prompt_retains_negative_regression(self):
        scene,spec=self.fixture();legacy=scene+' Move the book by 10 cm.'
        old=build_baseline_brief(legacy,'study');new=build_baseline_brief(separate(scene,spec)['scene_description'],'study')
        self.assertTrue(all(o['dimension_policy'].get('request_origin')!='inferred_category_prior' for o in old['objects']))
        self.assertTrue(all(o['dimension_policy'].get('request_origin')=='inferred_category_prior' for o in new['objects']))

    def test_invalid_task_units_and_numbers_rejected(self):
        scene,spec=self.fixture();spec['translation_frame']='world_centimeters'
        with self.assertRaises(ValueError):separate(scene,spec)
        spec['translation_frame']='support_local';spec['goal_offset_xy_m']=[float('nan'),0.]
        with self.assertRaises(ValueError):separate(scene,spec)
