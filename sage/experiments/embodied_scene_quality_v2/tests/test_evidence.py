from copy import deepcopy
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import numpy as np

from sage.experiments.embodied_scene_quality_v2.contracts import (
    Rejected, read, digest, reference, write_new, decisions)
from sage.experiments.embodied_scene_quality_v2.evidence import assess, load_admitted
from sage.experiments.embodied_scene_quality_v2.primitives import read_raw, evaluate_trace
from sage.experiments.embodied_scene_quality_v2.geometry import outside_pieces, fidelity, fidelity_passed
from sage.experiments.embodied_scene_quality_v2.__main__ import main


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import mujoco
        cls.root = Path(os.environ['SCENE_PRIMITIVE_ROOT'])
        cls.record = read(cls.root/'QUALITY.json'); cls.bundle = read(cls.root/'BUNDLE.json')
        cls.binding = read(cls.bundle['binding']['path']); cls.protocol = read(cls.root/'protocol/PROTOCOL.json')
        cls.ppin = digest(cls.root/'protocol/PROTOCOL.json'); cls.bpin = digest(cls.root/'BUNDLE.json')
        cls.rpin = digest(cls.root/'QUALITY.json'); cls.scope = cls.record['scope_sha256']
        cls.guards = [patch.object(mujoco, name, side_effect=AssertionError('new_physics_forbidden:'+name))
                      for name in ('MjData', 'mj_step', 'mj_step1', 'mj_step2', 'mj_forward', 'mj_resetData')]
        for guard in cls.guards: guard.start()

    @classmethod
    def tearDownClass(cls):
        for guard in cls.guards: guard.stop()

    def fixture(self, key, bundle_edit=None, binding_edit=None):
        root = self.root/'tests'/key; (root/'protocol').mkdir(parents=True, exist_ok=False)
        shutil.copyfile(self.root/'protocol/PROTOCOL.json', root/'protocol/PROTOCOL.json')
        bundle = deepcopy(self.bundle)
        if binding_edit:
            binding = deepcopy(self.binding); binding_edit(binding, root)
            write_new(root/'BINDING.json', binding); bundle['binding'] = reference(root/'BINDING.json')
        if bundle_edit: bundle_edit(bundle, root)
        write_new(root/'BUNDLE.json', bundle)
        return root, digest(root/'BUNDLE.json')

    def test_01_real_inspection_entry_passes_without_physics(self):
        model, receipt = load_admitted(self.root, self.root/'QUALITY.json', self.rpin,
            purpose='candidate_inspection', expected_scope_sha256=self.scope)
        self.assertGreater(model.ngeom, 0); self.assertEqual(receipt['physics_steps_started'], 0)
        write_new(self.root/'tests/INSPECTION_RECEIPT.json', receipt)

    def test_02_real_export_entry_denies_without_output(self):
        out = self.root/'tests/MUST_NOT_EXPORT.json'
        self.assertEqual(main(['admit','--root',str(self.root),'--record',str(self.root/'QUALITY.json'),
            '--record-sha256',self.rpin,'--scope-sha256',self.scope,'--use','qualified_export','--output',str(out)]), 2)
        self.assertFalse(out.exists())

    def test_03_record_pin_change_rejected(self):
        with self.assertRaisesRegex(Rejected, 'evidence_changed'):
            load_admitted(self.root,self.root/'QUALITY.json','0'*64,purpose='candidate_inspection',expected_scope_sha256=self.scope)

    def test_04_requested_scope_change_rejected(self):
        with self.assertRaisesRegex(Rejected, 'requested_scope_mismatch'):
            load_admitted(self.root,self.root/'QUALITY.json',self.rpin,purpose='isolated_release_cases',expected_scope_sha256='0'*64)

    def test_05_model_change_invalidates_evidence(self):
        def edit(binding, root):
            ref=binding['variants']['candidate']['xml'];target=root/'changed.xml'
            target.write_bytes(Path(ref['path']).read_bytes()+b' ');ref['path']=str(target)
        root,pin=self.fixture('model_change',binding_edit=edit)
        with self.assertRaisesRegex(Rejected, 'evidence_changed'):
            assess(root,self.ppin,pin)

    def test_06_task_binding_mismatch_rejected(self):
        root,pin=self.fixture('task_change',binding_edit=lambda b,r:b.update(source_task_sha256='0'*64))
        with self.assertRaisesRegex(Rejected, 'task_binding_mismatch'):
            assess(root,self.ppin,pin)

    def test_07_protocol_change_invalidates_receipt(self):
        root,pin=self.fixture('protocol_change')
        with (root/'protocol/PROTOCOL.json').open('a') as f:f.write(' ')
        with self.assertRaisesRegex(Rejected, 'evidence_changed'):
            assess(root,self.ppin,pin)

    def test_08_missing_dynamic_evidence_remains_unknown(self):
        def edit(bundle, root):
            bundle['trials']={k:v for k,v in bundle['trials'].items() if not k.startswith('candidate/')}
        root,pin=self.fixture('missing_dynamic',bundle_edit=edit)
        result=assess(root,self.ppin,pin)
        self.assertEqual(result['metrics']['dynamic_release']['state'],'unknown')
        self.assertFalse(result['qualification']['isolated_release_cases']['qualified'])

    def test_09_missing_raw_evidence_rejected(self):
        def edit(bundle, root):
            label=next(iter(bundle['trials']));attempt=read(bundle['trials'][label]['path'])
            attempt['raw']['path']=str(root/'MISSING.npz');write_new(root/'ATTEMPT.json',attempt)
            bundle['trials'][label]=reference(root/'ATTEMPT.json')
        root,pin=self.fixture('missing_raw',bundle_edit=edit)
        with self.assertRaisesRegex(Rejected, 'missing_evidence'):
            assess(root,self.ppin,pin)

    def trace_fixture(self):
        ref=self.bundle['trials']['candidate/settle_1mm'];attempt=read(ref['path'])
        raw=read_raw(attempt['raw']);initial=read(attempt['initial']['path'])
        task=read(Path(self.protocol['source_package'])/'task.json')
        return raw,initial,attempt,self.binding['variants']['candidate']['description'],task,self.protocol

    def test_10_zero_support_is_recomputed_as_failure(self):
        raw,initial,attempt,desc,task,protocol=self.trace_fixture()
        raw['contacts'][:,9:15]=0
        attempt['placement_stable']=True  # Deliberately forged summary; never used.
        result=evaluate_trace(raw,initial,attempt,desc,task,protocol)
        self.assertFalse(result['placement_stable'])

    def test_11_saved_state_and_pose_mismatch_rejected(self):
        args=list(self.trace_fixture());args[0]['qpos'][0,0]+=.01
        with self.assertRaisesRegex(Rejected, 'state_pose_velocity_mismatch'):
            evaluate_trace(*args)

    def test_12_contact_category_mismatch_rejected(self):
        args=list(self.trace_fixture());self.assertGreater(len(args[0]['contacts']),0)
        args[0]['contacts'][0,3]=99
        with self.assertRaisesRegex(Rejected, 'contact_category_mismatch'):
            evaluate_trace(*args)

    def test_13_nonfinite_raw_evidence_rejected(self):
        args=list(self.trace_fixture());args[0]['qvel'][0,0]=np.nan
        with self.assertRaisesRegex(Rejected, 'nonfinite_raw_evidence'):
            evaluate_trace(*args)

    def test_14_required_metric_not_applicable_cannot_waive(self):
        metrics=deepcopy(self.record['metrics'])
        for value in metrics.values():value['state']='pass'
        metrics['numerical_reliability']['state']='not_applicable'
        self.assertFalse(decisions(metrics)['isolated_release_cases']['qualified'])

    def test_15_source_holes_do_not_receive_invented_columns(self):
        with np.load(self.root/'geometry/CONSTRUCTION_SAMPLES.npz') as data:
            expected=np.isfinite(data['source_upper']) & np.isfinite(data['source_lower']) & (data['source_upper']-data['source_lower']>1e-9)
            np.testing.assert_array_equal(expected,data['accepted_cell'])
            self.assertGreater(np.count_nonzero(~data['accepted_cell']),0)

    def test_16_roi_partition_preserves_outside_volume(self):
        roi=np.array([[-.055,-.11],[.055,.11]])
        center=np.array([0.,0.,-.15]);size=np.array([.2,.2,.01])
        pieces=outside_pieces(center,size,roi)
        remaining=sum(np.prod(2*s) for c,s in pieces)
        self.assertAlmostEqual(remaining,np.prod(2*size)-np.prod(roi[1]-roi[0])*.02,places=12)
        for c,s in pieces:
            self.assertTrue(np.any((c+s)[:2]<=roi[0]+1e-12) or np.any((c-s)[:2]>=roi[1]-1e-12))

    def test_17_bad_geometry_is_not_a_pass(self):
        measurement=fidelity(np.zeros(10),np.full(10,.1))
        self.assertFalse(fidelity_passed(measurement,self.protocol['geometry']['qualification']))

    def test_18_forged_qualification_rejected_by_raw_recomputation(self):
        record=deepcopy(self.record);record['metrics']['full_robot_task']['state']='pass'
        record['metrics']['full_robot_task']['evidence']=['fabricated-test-only']
        record['qualification']=decisions(record['metrics'])
        path=self.root/'tests/FORGED_RECORD.json';write_new(path,record)
        with self.assertRaisesRegex(Rejected, 'record_assessment_changed'):
            load_admitted(self.root,path,digest(path),purpose='qualified_collection',expected_scope_sha256=self.scope)

    def test_19_model_scope_binding_rejected(self):
        root,pin=self.fixture('scope_change',binding_edit=lambda b,r:b.update(scope_sha256='0'*64))
        with self.assertRaisesRegex(Rejected, 'scope_binding_mismatch'):
            assess(root,self.ppin,pin)

    def test_20_all_declared_cases_counted_and_budget_bound(self):
        self.assertEqual(len(self.record['all_attempts']),29)
        self.assertEqual(self.record['cost']['attempts'],29)
        self.assertLessEqual(self.record['cost']['new_physics_steps'],80000)
        self.assertFalse(self.record['qualification']['qualified_collection']['qualified'])
        self.assertFalse(self.record['qualification']['qualified_export']['qualified'])


if __name__=='__main__':unittest.main()
