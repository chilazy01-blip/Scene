import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from .. import METHOD_VERSION, QUALITY_VERSION
from ..quality import QualityContract, support_window, phase_contacts, foot_transients, continuous_transport, contact_dynamics
from ..admission import AdmissionError, check, claim, sha
from ..pipeline import run_operation
from ..acceptance import REQUIRED, accept_episode, accept_batch
from ..progress import CoordinatedPath, ControlRejected, validate_ik, ManipulationState, grasp_state


class ProgressTests(unittest.TestCase):
    def test_measured_progress_bounds_every_arm_and_finger_channel(self):
        target=[-.3+i*.03 for i in range(31)]
        path=CoordinatedPath([[0.]*31,target,[0.]*31])
        actual=[0.]*31;last=actual[:];velocity=actual[:];braked=False
        for i in range(1500):
            observed=[a-.1 for a in actual] if 15<=i<23 else actual
            command,meta=path.step(observed,lambda a,b,stop:True)
            new_velocity=[(a-b)/.02 for a,b in zip(command,last)]
            self.assertLessEqual(max(map(abs,new_velocity)),1.+1e-7)
            self.assertLessEqual(max(abs(a-b)/.02 for a,b in zip(new_velocity,velocity)),4.+1e-7)
            ratios=[a/b for a,b in zip(command,target) if abs(b)>1e-9]
            self.assertLess(max(ratios)-min(ratios),1e-8)
            braked=braked or meta.get('braking',False)
            actual=last=command;velocity=new_velocity
            if meta['finished']:break
        self.assertTrue(path.finished)
        self.assertTrue(braked)
        self.assertLess(max(map(abs,command)),1e-7)

    def test_unreachable_ik_and_unsafe_stop_never_advance(self):
        with self.assertRaises(ControlRejected):
            validate_ik({s:dict(position=.07,rotation=0.,condition=10.) for s in ['left','right']})
        path=CoordinatedPath([[0.,0.],[1.,.5]])
        with self.assertRaises(ControlRejected):path.step([0.,0.],lambda *args:False)
        self.assertEqual(path.last,[0.,0.])
        self.assertEqual(path.u,0.)

    def test_loss_of_grasp_is_a_transition_failure(self):
        state=ManipulationState();state.phase='carry'
        with self.assertRaises(ControlRejected):
            state.update(grasped=False,slipped=False,lifted=True,at_standoff=False,settled=False,
                         placement_ready=False,supported=False,released=False,withdrawal_done=False,terminal_passed=False)
        self.assertFalse(grasp_state(1,1,.02,.1,0.,2.45,displacement_limit=.005,speed_limit=.02)['grasped'])


class AcceptanceTests(unittest.TestCase):
    def test_single_success_cannot_open_batch_data_gate(self):
        binding={k:'a'*64 for k in ['trace_sha256','model_sha256','controller_sha256','quality_contract_sha256','calibration_sha256']}
        checks={k:True for k in REQUIRED}
        one=accept_episode('h1',checks,binding,source_role='holdout')
        self.assertTrue(one['episode_passed'])
        self.assertFalse(one['data_passed'])
        self.assertFalse(accept_batch(['h1','h2','h3','h4'],[one],closed=False)['data_capture_admitted'])
        checks['contact_dynamics']='not_calibrated'
        self.assertFalse(accept_episode('h1',checks,binding,source_role='holdout')['episode_passed'])

    def test_closed_or_incomplete_batch_never_passes(self):
        episodes=[dict(episode_id='h'+str(i),episode_passed=True,quality_version=QUALITY_VERSION,source_role='holdout') for i in range(4)]
        ids=[e['episode_id'] for e in episodes]
        self.assertTrue(accept_batch(ids,episodes,closed=False)['batch_passed'])
        self.assertFalse(accept_batch(ids,episodes,closed=True)['batch_passed'])
        episodes[0]['source_role']='regression'
        self.assertFalse(accept_batch(ids,episodes,closed=False)['batch_passed'])

class QualityTests(unittest.TestCase):

    def setUp(self):
        self.contract = QualityContract()
        self.sample = dict(bottom_margin=0.01, com_margin=0.02, board_vertical_load=2.4525, weight=2.4525, force_residual=0.0, other_support_load=0.0, hand_contacts=0, object_linear=0.0, object_angular=0.0)
        self.rows = [dict(self.sample, time=i * 0.005) for i in range(200)]

    def test_real_duration_and_full_independent_support(self):
        self.assertTrue(support_window(self.rows, self.contract)['passed'])
        for key, value in (('bottom_margin', -0.04), ('board_vertical_load', 0.001), ('other_support_load', 1.0), ('hand_contacts', 1), ('com_margin', -0.01), ('force_residual', 1.0), ('object_linear', float('nan'))):
            with self.subTest(key=key):
                bad = copy.deepcopy(self.rows)
                bad[-1][key] = value
                self.assertFalse(support_window(bad, self.contract)['passed'])
        self.assertFalse(support_window(self.rows[:100], self.contract)['passed'])
        self.rows[-1]['time'] += 0.005
        self.assertFalse(support_window(self.rows, self.contract)['passed'])

    def test_stage_contact_ignores_legacy_allowed_flag(self):
        roles = {'box': 'object', 'board': 'environment', 'hand': 'hand', 'cabinet': 'environment'}
        contact = dict(geoms=['box', 'board'], distance=-0.001, normal_force=10.0, allowed=True)
        self.assertFalse(phase_contacts([contact], 'carry', roles, 'board')['passed'])
        self.assertTrue(phase_contacts([contact], 'place', roles, 'board')['passed'])
        contact['geoms'] = ['hand', 'board']
        self.assertFalse(phase_contacts([contact], 'withdraw', roles, 'board')['passed'])
        contact['geoms'] = ['box', 'cabinet']
        self.assertFalse(phase_contacts([contact], 'place', roles, 'board')['passed'])
        self.assertFalse(phase_contacts([], 'typo', roles, 'board')['passed'])

    def test_transients_keep_trimmed_edges_and_do_not_invent_impulse(self):
        rows = [dict(time=i * 0.005, foot_load=dict(left=100.0, right=100.0), foot_slip=dict(left=0.85 if i < 8 else 0.001, right=0.001)) for i in range(30)]
        r = foot_transients(rows, self.contract)
        self.assertFalse(r['passed'])
        self.assertEqual(r['events'][0]['peak_contact_speed'], 0.85)
        self.assertIsNone(r['events'][0]['impulse_Ns'])
        self.assertEqual(len(foot_transients(rows[:2], self.contract)['events']), 4)
        self.assertFalse(contact_dynamics([dict(force_semantics='query', force_norm=1.0, approach_speed=0.0, dt=0.005)], self.contract)['passed'])

    def test_steps_cannot_be_spliced_with_separate_transport(self):
        roles = {'box': 'object', 'board': 'environment'}
        rows = [dict(time=i * 0.005, object_position=[i * 0.001, 0.0, 0.1], hand_contacts=2, contacts=[]) for i in range(500)]
        swings = [dict(side='left' if i % 2 == 0 else 'right', start=0.1 + i * 0.2, end=0.2 + i * 0.2, duration=0.1, opposite_min_load=100.0) for i in range(4)]
        self.assertTrue(continuous_transport(rows, swings, 0.0, roles)['passed'])
        for i in range(170, 175):
            rows[i]['hand_contacts'] = 0
        self.assertFalse(continuous_transport(rows, swings, 0.0, roles)['passed'])

class AdmissionTests(unittest.TestCase):

    def test_diagnostic_regression_never_substitutes_for_calibrated_execution(self):
        a=self.admission()
        a['quality_calibration_passed']=False
        a['cases']['new_case']=dict(role='regression',seen=True,production_eligible=False)
        with self.assertRaisesRegex(AdmissionError,'diagnostic_protocol_required'):
            check(a,'regress','new_case')
        a['diagnostic_protocol_frozen']=True
        self.assertEqual(check(a,'regress','new_case')['role'],'regression')
        for operation in ('execute','capture','export'):
            with self.assertRaisesRegex(AdmissionError,'quality_calibration_required'):
                check(a,operation,'new_case')
        a['cases']['new_case']=dict(role='holdout',seen=False,production_eligible=False)
        with self.assertRaisesRegex(AdmissionError,'regression_role_required'):
            check(a,'regress','new_case')
        with self.assertRaisesRegex(AdmissionError,'development_role_required'):
            check(a,'develop','new_case')
        a['cases']['new_case']=dict(role='development',seen=True,production_eligible=False)
        self.assertEqual(check(a,'develop','new_case')['role'],'development')
        with self.assertRaisesRegex(AdmissionError,'quality_calibration_required'):
            check(a,'capture','new_case')

    def admission(self):
        return dict(schema='fullbody-admission/v2', method_version=METHOD_VERSION, quality_version=QUALITY_VERSION, batch_state='open', authorized=True, deadline_epoch=9999999999, resource_reserve_verified=True, preflight_passed=True, quality_calibration_passed=True, cases={'new_case': dict(role='holdout', seen=False)})

    def test_every_entry_rejects_closed_and_unqualified_batch(self):
        a = self.admission()
        a['batch_state'] = 'closed'
        for op in ('execute', 'capture', 'export'):
            with self.assertRaisesRegex(AdmissionError, 'batch_closed'):
                check(a, op, 'new_case')
        a = self.admission()
        for op in ('capture', 'export'):
            with self.assertRaisesRegex(AdmissionError, 'batch_not_passed'):
                check(a, op, 'new_case')
        a['cases']['new_case']['seen'] = True
        with self.assertRaisesRegex(AdmissionError, 'seen_case'):
            check(a, 'execute', 'new_case')

    def test_failed_operation_consumes_case_and_input_changes_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            source = root / 'source'
            source.write_text('frozen')
            a = self.admission()
            a['files'] = {str(source): sha(source)}
            manifest = root / 'admission.json'
            manifest.write_text(json.dumps(a))
            with self.assertRaises(RuntimeError):
                with claim(manifest, 'execute', 'new_case'):
                    raise RuntimeError('worker_failed')
            with self.assertRaisesRegex(AdmissionError, 'already_consumed'):
                with claim(manifest, 'execute', 'new_case'):
                    pass
            source.write_text('changed')
            with self.assertRaisesRegex(AdmissionError, 'frozen_input'):
                with claim(manifest, 'execute', 'new_case'):
                    pass

    def test_closed_worker_rejects_before_backend_import(self):
        with tempfile.TemporaryDirectory() as t:
            manifest = Path(t) / 'admission.json'
            a = self.admission()
            a['batch_state'] = 'closed'
            manifest.write_text(json.dumps(a))
            with patch('importlib.import_module') as loader:
                for op in ('execute', 'capture', 'export'):
                    with self.assertRaisesRegex(AdmissionError, 'batch_closed'):
                        run_operation(manifest, op, 'new_case', 'unloaded_backend')
                loader.assert_not_called()
