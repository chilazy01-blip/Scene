"""Software contract tests. Fixtures confer no physical qualification."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import intake as api
from .__main__ import main


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.task = dict(task='place_in_container', split='development', goal=[1., 2., 3.],
            target_quat=[1., 0., 0., 0.], target_semantic_id='object',
            container_semantic_id='receptacle', support_semantic_id='table')
        self.model = dict(kind='source_package', format='mjcf', sha256='a'*64)
        self.scope = api.unknown_scope(self.task)
        self.intent = dict(schema='asset-task-intent/v1', task_sha256='b'*64,
            roles=dict(target='object', container='receptacle', support='table'),
            placement=dict(goal_m=self.task['goal'], quaternion_wxyz=self.task['target_quat']),
            model=self.model, scope=self.scope)

    def check_intent(self, value):
        api.validate_intent(value, self.task, 'b'*64, self.model, self.scope)

    def test_explicit_matching_intent(self):
        self.check_intent(self.intent)

    def test_changed_task(self):
        value = deepcopy(self.intent); value['task_sha256'] = 'c'*64
        with self.assertRaisesRegex(api.Rejected, 'task_mismatch'): self.check_intent(value)

    def test_reversed_roles(self):
        value = deepcopy(self.intent); value['roles']['target'] = 'receptacle'
        with self.assertRaisesRegex(api.Rejected, 'role_mismatch'): self.check_intent(value)

    def test_changed_posture(self):
        value = deepcopy(self.intent); value['placement']['quaternion_wxyz'] = [0., 1., 0., 0.]
        with self.assertRaisesRegex(api.Rejected, 'placement_mismatch'): self.check_intent(value)

    def test_changed_goal(self):
        value = deepcopy(self.intent); value['placement']['goal_m'][0] += .01
        with self.assertRaisesRegex(api.Rejected, 'placement_mismatch'): self.check_intent(value)

    def test_candidate_cannot_inherit_source_model_qualification(self):
        value = deepcopy(self.intent); value['model']['kind'] = 'primitive_candidate'
        with self.assertRaisesRegex(api.Rejected, 'model_mismatch'): self.check_intent(value)

    def test_expanded_scope(self):
        value = deepcopy(self.intent); value['scope']['continuous_range_validated'] = True
        with self.assertRaisesRegex(api.Rejected, 'scope_mismatch'): self.check_intent(value)

    def test_missing_scope(self):
        value = deepcopy(self.intent); del value['scope']
        with self.assertRaisesRegex(api.Rejected, 'intent_fields'): self.check_intent(value)

    def test_caller_cannot_replace_required_metrics(self):
        value = deepcopy(self.intent); value['required'] = ['input_binding']
        with self.assertRaisesRegex(api.Rejected, 'intent_fields'): self.check_intent(value)

    def test_nonfinite_input(self):
        value = deepcopy(self.intent); value['placement']['goal_m'][0] = float('nan')
        with self.assertRaisesRegex(api.Rejected, 'invalid_intent'): self.check_intent(value)

    def test_semantic_rename_not_historical_name_dependency(self):
        task = deepcopy(self.task); objects = []; assets = []; sources = {}
        for index, role in enumerate(('target', 'container', 'support')):
            name = 'renamed_' + str(index); task[role + '_semantic_id'] = name
            task[role + '_body'] = 'body_' + name
            objects.append(dict(semantic_id=name, body='body_' + name, category='fixture',
                actual_dimensions_m=[1, 1, 1], pose_z_up=[], collider='fixture', mass_kg=.25,
                inertia_origin='prior', friction=.5, measured=False))
            assets.append(dict(object_id=name, asset_id='asset_' + name))
            sources['asset:' + name] = dict(path=name, sha256='0'*64)
        result = api.describe_roles(task, dict(objects=objects, asset_resolution=assets), sources)
        self.assertEqual(result['target']['semantic_id'], 'renamed_0')
        self.assertEqual(result['container']['source_asset'], sources['asset:renamed_1'])

    def test_inspection_never_promotes_learning(self):
        qualifiers = {name: dict(qualified=True, reasons=[]) for name in api.USES}
        learning = api.downstream_requirements(qualifiers)[-1]
        self.assertFalse(learning['qualified'])
        self.assertIn('learning_input_numerics:unknown', learning['reasons'])

    def test_wrong_combination_stops_before_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'record.json'; api.write_new(path, dict(combination_id='actual'))
            with patch.object(api, 'revalidate_task') as checked:
                with self.assertRaisesRegex(api.Rejected, 'requested_combination_mismatch'):
                    api.open_task(path, api.digest(path), purpose='candidate_inspection', expected_combination_id='other')
                checked.assert_not_called()

    def test_forged_pass_recomputed_before_native_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'record.json'
            saved = dict(schema=api.SCHEMA, implementation=api.implementation(), inputs={}, combination_id='x',
                         qualification={'qualified_collection': {'qualified': True, 'reasons': []}})
            actual = deepcopy(saved); actual['qualification']['qualified_collection']['qualified'] = False
            api.write_new(path, saved)
            with patch.object(api, 'prepare_task', return_value=actual), patch.object(api.primitive, 'load_admitted') as loader:
                with self.assertRaisesRegex(api.Rejected, 'intake_content_or_evidence_changed'):
                    api.open_task(path, api.digest(path), purpose='qualified_collection', expected_combination_id='x')
                loader.assert_not_called()

    def test_unknown_use_stops_before_reading(self):
        with self.assertRaisesRegex(api.Rejected, 'unsupported_use'):
            api.open_task('/missing', 'a'*64, purpose='training', expected_combination_id='x')

    def test_output_cannot_touch_input_trees(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = dict(inputs=dict(package=tmp, generator_output='/unused', primitive_record=None))
            with self.assertRaisesRegex(api.Rejected, 'must_not_modify_frozen_inputs'):
                api.write_intake(Path(tmp)/'new.json', value)
            self.assertFalse((Path(tmp)/'new.json').exists())

    def test_outputs_are_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'new.json'
            value = dict(inputs=dict(package='/unused', generator_output='/also_unused', primitive_record=None))
            api.write_intake(path, value)
            with self.assertRaises(FileExistsError): api.write_intake(path, value)

    def test_cli_missing_request_has_no_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)/'output.json'
            self.assertEqual(main(['prepare', '--request', str(Path(tmp)/'missing.json'),
                '--request-sha256', 'a'*64, '--output', str(out)]), 2)
            self.assertFalse(out.exists())
