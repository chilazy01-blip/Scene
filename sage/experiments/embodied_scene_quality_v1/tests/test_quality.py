"""Run under the registered CPU service with SCENE_QUALITY_FIXTURE pointing to a copy."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from sage.experiments.embodied_scene_quality_v1 import quality
from sage.experiments.embodied_scene_quality_v1.__main__ import main
from sage.experiments.embodied_scene_quality_v1.contracts import (
    Rejected, digest, fingerprint, read, write_new)


class QualityIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mujoco
        cls.root = Path(os.environ['SCENE_QUALITY_FIXTURE'])
        cls.package = cls.root / 'package'
        cls.sources = read(cls.root / 'sources.json')
        cls.counter = 0
        # These tests must never initialize/step a simulator, including indirectly.
        cls.guards = [patch.object(mujoco, name, side_effect=AssertionError('physics_forbidden:' + name))
                      for name in ('mj_step', 'mj_step1', 'mj_step2', 'mj_forward', 'mj_resetData', 'MjData')]
        for p in cls.guards:
            p.start()
        cls.record = quality.create_record(cls.package, cls.sources)
        cls.good = cls.root / 'good_record.json'; write_new(cls.good, cls.record)
        cls.pin = digest(cls.good)

    @classmethod
    def tearDownClass(cls):
        for p in cls.guards:
            p.stop()

    def save(self, value):
        type(self).counter += 1
        path = self.root / ('test_record_%02d.json' % self.counter)
        write_new(path, value)
        return path, digest(path)

    @contextmanager
    def change(self, relative, edit, *, renew=False):
        path = self.package / relative
        original = path.read_bytes(); manifest = (self.package / 'FILES.json').read_bytes()
        try:
            path.write_bytes(edit(original))
            if renew:
                files = json.loads(manifest); files[relative] = digest(path)
                (self.package / 'FILES.json').write_text(json.dumps(files))
            yield
        finally:
            path.write_bytes(original); (self.package / 'FILES.json').write_bytes(manifest)

    def changed_json(self, relative, edit, **kwargs):
        def change(data):
            value = json.loads(data); edit(value)
            return json.dumps(value).encode()
        return self.change(relative, change, **kwargs)

    def changed_xml(self, edit, **kwargs):
        def change(data):
            root = ET.fromstring(data); edit(root)
            return ET.tostring(root)
        return self.change('model.xml', change, **kwargs)

    def assert_unqualified(self, record, reason):
        found = record['assessment']
        self.assertFalse(found['qualification']['static_inspection']['qualified'])
        self.assertIn(reason, json.dumps(found))
        path, pin = self.save(record)
        with self.assertRaises(Rejected):
            quality.load_admitted(self.package, path, pin, purpose='static_inspection')

    def test_01_actual_model_preflight_passes_only_static(self):
        findings = self.record['assessment']
        self.assertTrue(findings['qualification']['static_inspection']['qualified'], json.dumps(findings))
        self.assertEqual(findings['metrics']['dynamic_release']['state'], 'unknown')
        self.assertEqual(findings['metrics']['environment_articulation']['state'], 'not_applicable')
        model, receipt = quality.load_admitted(self.package, self.good, self.pin, purpose='static_inspection')
        self.assertGreater(model.ngeom, 4912)
        self.assertEqual(receipt['subject']['task_sha256'], digest(self.package / 'task.json'))
        write_new(self.root / 'API_PREFLIGHT_RECEIPT.json', receipt)

    def test_02_cli_real_entry_success_and_export_denial(self):
        out = self.root / 'CLI_PREFLIGHT.json'
        self.assertEqual(main(['preflight', '--package', str(self.package), '--record', str(self.good),
            '--record-sha256', self.pin, '--use', 'static_inspection', '--output', str(out)]), 0)
        denied = self.root / 'MUST_NOT_EXPORT.json'
        self.assertEqual(main(['preflight', '--package', str(self.package), '--record', str(self.good),
            '--record-sha256', self.pin, '--use', 'qualified_export', '--output', str(denied)]), 2)
        self.assertFalse(denied.exists())

    def test_03_required_dynamic_evidence_denies_before_loading(self):
        with patch('sage.experiments.embodied_scene_quality_v1.quality.assess', side_effect=AssertionError('must_not_load')):
            for use in ('qualified_collection', 'qualified_export'):
                with self.assertRaisesRegex(Rejected, 'unqualified_use:'):
                    quality.load_admitted(self.package, self.good, self.pin, purpose=use)

    def test_04_model_task_and_asset_changes_invalidate_receipt(self):
        asset = next(name for name in read(self.package / 'FILES.json') if name.endswith('.stl'))
        for relative in ('model.xml', 'task.json', asset):
            with self.subTest(relative=relative), self.change(relative, lambda b: b+b' '):
                with self.assertRaisesRegex(Rejected, 'record_evidence_or_assessment_changed'):
                    quality.load_admitted(self.package, self.good, self.pin, purpose='static_inspection')

    def test_05_missing_layout_stays_unknown(self):
        sources = dict(self.sources); sources.pop('layout')
        record = quality.create_record(self.package, sources)
        self.assertEqual(record['assessment']['metrics']['source_binding']['state'], 'unknown')
        self.assertEqual(record['assessment']['metrics']['coordinates_dimensions']['state'], 'unknown')
        self.assert_unqualified(record, 'layout')

    def test_06_wrong_units_rejected_even_with_refreshed_hashes(self):
        path = Path(self.sources['layout']); original = path.read_bytes()
        try:
            layout = json.loads(original); layout['coordinate_contract']['units'] = 'cm'
            path.write_text(json.dumps(layout))
            with self.changed_json('scene_manifest.json', lambda d: d.update(layout_sha256=digest(path)), renew=True):
                self.assert_unqualified(quality.create_record(self.package, self.sources), 'coordinate_units_or_axes_mismatch')
        finally:
            path.write_bytes(original)

    def test_07_inconsistent_mass_and_inertia_rejected(self):
        body_name = self.record['assessment']['scope']['target_body']
        for key, value in (('mass', '.3'), ('diaginertia', '.001 .001 .001')):
            with self.subTest(key=key), self.changed_xml(
                    lambda r: r.find(".//body[@name='"+body_name+"']/inertial").set(key, value), renew=True):
                self.assert_unqualified(quality.create_record(self.package, self.sources), 'mass_or_bbox_inertia_mismatch')

    def test_08_friction_and_solver_readback_rejected(self):
        for path, key, value, reason in [('default/geom', 'friction', '.9 .005 .0001', 'contact_declaration_mismatch'),
                                        ('option', 'timestep', '.002', 'solver_or_timestep_declaration_mismatch')]:
            with self.subTest(key=key), self.changed_xml(lambda r: r.find(path).set(key, value), renew=True):
                self.assert_unqualified(quality.create_record(self.package, self.sources), reason)

    def test_09_unsupported_joint_layout_rejected(self):
        name = self.record['assessment']['scope']['target_body']
        def edit(root):
            body = root.find(".//body[@name='"+name+"']"); body.remove(body.find('freejoint'))
            ET.SubElement(body, 'joint', name='arbitrary_hinge', type='hinge')
        with self.changed_xml(edit, renew=True):
            self.assert_unqualified(quality.create_record(self.package, self.sources), 'unsupported_model_layout:target_joint')

    def test_10_record_pin_and_implementation_changes_rejected(self):
        record = deepcopy(self.record); record['implementation']['version'] = 'fake'
        path, pin = self.save(record)
        with self.assertRaisesRegex(Rejected, 'record_digest_mismatch'):
            quality.load_admitted(self.package, path, self.pin, purpose='static_inspection')
        with self.assertRaisesRegex(Rejected, 'quality_implementation_changed'):
            quality.load_admitted(self.package, path, pin, purpose='static_inspection')

    def test_11_forged_dynamic_pass_cannot_issue_receipt(self):
        from sage.experiments.embodied_scene_quality_v1.contracts import qualifications
        record = deepcopy(self.record)
        for m in record['assessment']['metrics'].values():
            if m['state'] == 'unknown':
                m.update(state='pass', evidence=['fabricated_physical_evidence'], reason='fabricated test only')
        record['assessment']['qualification'] = qualifications(record['assessment']['metrics'])
        path, pin = self.save(record)
        with self.assertRaisesRegex(Rejected, 'record_evidence_or_assessment_changed'):
            quality.load_admitted(self.package, path, pin, purpose='qualified_export')

    def test_12_not_applicable_cannot_waive_required_metric(self):
        from sage.experiments.embodied_scene_quality_v1.contracts import qualifications
        record = deepcopy(self.record); m = record['assessment']['metrics']['dynamic_release']
        m.update(state='not_applicable', applicability=dict(applicable=False, explanation='invalid waiver test'))
        record['assessment']['qualification'] = qualifications(record['assessment']['metrics'])
        path, pin = self.save(record)
        with self.assertRaisesRegex(Rejected, 'dynamic_release:not_applicable'):
            quality.load_admitted(self.package, path, pin, purpose='qualified_collection')

    def test_13_missing_required_metric_cannot_lower_policy(self):
        from sage.experiments.embodied_scene_quality_v1.contracts import qualifications
        record = deepcopy(self.record); del record['assessment']['metrics']['physical_parameters']
        record['assessment']['qualification'] = qualifications(record['assessment']['metrics'])
        path, pin = self.save(record)
        with self.assertRaisesRegex(Rejected, 'physical_parameters:missing'):
            quality.load_admitted(self.package, path, pin, purpose='static_inspection')

    def test_14_historical_report_change_invalidates_record(self):
        path = Path(self.sources['legacy_static_load']); original = path.read_bytes()
        try:
            path.write_bytes(original+b' ')
            with self.assertRaisesRegex(Rejected, 'record_evidence_or_assessment_changed'):
                quality.load_admitted(self.package, self.good, self.pin, purpose='static_inspection')
        finally:
            path.write_bytes(original)

    def test_15_nonfinite_and_duplicate_json_rejected(self):
        for transform in (lambda b: b.replace(b'0.02', b'NaN', 1),
                          lambda b: b.replace(b'{', b'{"task":"other",', 1)):
            with self.change('task.json', transform, renew=True):
                record = quality.create_record(self.package, self.sources)
                self.assertFalse(record['assessment']['qualification']['static_inspection']['qualified'])

    def test_16_manifest_traversal_rejected(self):
        with self.changed_json('FILES.json', lambda d: d.update({'../outside': '0'*64})):
            self.assert_unqualified(quality.create_record(self.package, self.sources), 'invalid_manifest_path:')

    def test_17_hidden_container_support_rejected(self):
        name = self.record['assessment']['scope']['container_body']
        def edit(root):
            ET.SubElement(root.find(".//body[@name='"+name+"']"), 'geom',
                          name='hidden_support', type='box', size='.1 .1 .005')
        with self.changed_xml(edit, renew=True):
            self.assert_unqualified(quality.create_record(self.package, self.sources), 'uncertified_container_collision_geometry')

    def test_18_legacy_pitch_guard_preserved(self):
        # Updating task alone is already inconsistent with its separate certificate.
        with self.changed_json('task.json', lambda d: d['cavity'].update(proxy_pitch_m=.0025), renew=True):
            self.assert_unqualified(quality.create_record(self.package, self.sources), 'task_certificate_mismatch')

    def test_19_passing_metric_requires_evidence(self):
        record = deepcopy(self.record); record['assessment']['metrics']['physical_parameters']['evidence'] = []
        path, pin = self.save(record)
        with self.assertRaisesRegex(Rejected, 'passing_metric_without_evidence'):
            quality.load_admitted(self.package, path, pin, purpose='static_inspection')

    def test_20_no_package_writes_and_no_overwrite(self):
        with self.assertRaisesRegex(Rejected, 'quality_sidecar_must_not_modify_package'):
            quality.write_sidecar(self.package, self.package/'FORBIDDEN.json', {})
        with self.assertRaises(FileExistsError):
            quality.write_sidecar(self.package, self.good, {})

    def test_21_task_pose_inconsistency_rejected_with_new_manifest(self):
        with self.changed_json('task.json', lambda d: d.update(start=[0, 0, 0]), renew=True):
            self.assert_unqualified(quality.create_record(self.package, self.sources), 'task_role_pose_declaration_mismatch')

    def test_22_development_combination_is_not_independent_validation(self):
        scope = self.record['assessment']['scope']
        self.assertEqual(scope['asset_support_combinations'], 1)
        self.assertEqual(scope['independent_validation_combinations'], 0)
        self.assertEqual(scope['split'], 'development')


if __name__ == '__main__':
    unittest.main()
