import unittest
from copy import deepcopy
from .semantic import validate_roles
from sage.experiments.embodied_scene_quality_v1.contracts import Rejected


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.objects=[dict(id='explicit_single_book',category='single_book',support_id='explicit_side_table',asset_id='book'),
            dict(id='explicit_side_table',category='side_table',asset_id='table')]
        self.roles=dict(target_id='explicit_single_book',support_id='explicit_side_table',target_category='single_book',
            support_category='side_table',target_asset_id='book',support_asset_id='table')
        self.counts=dict(single_book=1,side_table=1)
    def test_valid_unique_instances(self):self.assertEqual(validate_roles(self.objects,self.roles,self.counts)[0]['id'],'explicit_single_book')
    def test_category_is_not_instance_id(self):
        self.objects[0]['support_id']='side_table'
        with self.assertRaises(Rejected):validate_roles(self.objects,self.roles,self.counts)
    def test_duplicate_book_rejected(self):
        other=deepcopy(self.objects[0]);other['id']='task_target';self.objects.append(other)
        with self.assertRaises(Rejected):validate_roles(self.objects,self.roles,self.counts)
    def test_asset_substitution_rejected(self):
        self.objects[0]['asset_id']='other_book'
        with self.assertRaises(Rejected):validate_roles(self.objects,self.roles,self.counts)
    def test_renamed_instances_work(self):
        self.objects[0]['id']='item';self.objects[1]['id']='surface';self.objects[0]['support_id']='surface'
        self.roles.update(target_id='item',support_id='surface')
        validate_roles(self.objects,self.roles,self.counts)
