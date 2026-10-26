from copy import deepcopy
from pathlib import Path
import unittest

from sage.experiments.embodied_scene_bridge.contracts import (
    read, validate_protocol, validate_split_registry, select_task_objects)

ROOT = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_generator_m1_20260918_v1')


class Contracts(unittest.TestCase):
    def test_frozen_scope_and_repair_gate(self):
        protocol = read(ROOT/'protocol/PROTOCOL.json')
        self.assertTrue(validate_protocol(protocol))
        protocol['repairs']['new_task_repair_budget'] = 1
        with self.assertRaisesRegex(ValueError, 'M1_is_unmodified_generator_B'):
            validate_protocol(protocol)

    def test_disjoint_groups_and_no_empty_learning_split(self):
        rows = [dict(split=s,source_asset_groups=[s+'asset'],asset_content_sha256=[s+'hash'],layout_families=[s+'layout'])
                for s in ('train','validation','test')]
        self.assertTrue(validate_split_registry(rows,True))
        for field in ('source_asset_groups','asset_content_sha256','layout_families'):
            copy = deepcopy(rows);copy[2][field] = copy[0][field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,'split_leakage'):
                validate_split_registry(copy,True)
        with self.assertRaisesRegex(ValueError,'learning_splits_not_frozen'):
            validate_split_registry([],True)

    def test_historical_development_not_promoted(self):
        rows = [dict(split=s,source_asset_groups=['historic'],asset_content_sha256=[s],layout_families=[s])
                for s in ('development','test')]
        with self.assertRaisesRegex(ValueError,'split_leakage'):
            validate_split_registry(rows)

    def test_semantic_binding_independent_of_names_and_source_assets(self):
        request = read(ROOT/'requests/D02.json')
        for support_name,target_name,category in [('desk','manual','desk'),('arbitrary_surface','unseen_item','dining_table')]:
            scene = dict(objects=[dict(id=support_name,category=category),
                                  dict(id=target_name,category='single_book',support_id=support_name)])
            target,support = select_task_objects(scene,request)
            self.assertEqual((target['id'],support['id']),(target_name,support_name))

    def test_missing_ambiguous_support_or_target_fails(self):
        request = read(ROOT/'requests/D02.json')
        base = [dict(id='surface',category='desk'),dict(id='item',category='single_book',support_id='surface')]
        for objects in [base[:1],[dict(id='item',category='single_book',support_id='missing')],
                        base+[dict(id='second',category='single_book',support_id='surface')]]:
            with self.subTest(objects=objects), self.assertRaisesRegex(ValueError,'task_binding_not_unique'):
                select_task_objects(dict(objects=objects),request)

    def test_container_label_is_not_functional_cavity(self):
        request = read(ROOT/'requests/D02.json');request['task']='place_in_container'
        scene = dict(objects=[dict(id='surface',category='desk'),
            dict(id='item',category='single_book',support_id='surface'),dict(id='box',category='storage_box')])
        with self.assertRaisesRegex(ValueError,'verified_container_cavity_missing'):
            select_task_objects(scene,request)


if __name__ == '__main__':
    unittest.main()
