import json
from pathlib import Path
import tempfile
import unittest
from .. import METHOD_VERSION,QUALITY_VERSION
from ..admission import AdmissionError,check,claim,sha


class AdmissionTests(unittest.TestCase):
    def fixture(self):
        return dict(schema='fullbody-admission/v2',method_version=METHOD_VERSION,quality_version=QUALITY_VERSION,
            batch_state='open',authorized=True,deadline_epoch=9999999999,resource_reserve_verified=True,
            preflight_passed=True,quality_calibration_passed=False,diagnostic_protocol_frozen=True,
            cases={'case':dict(role='development',seen=True,production_eligible=False)})

    def test_diagnostic_success_cannot_open_production(self):
        admission=self.fixture()
        self.assertEqual(check(admission,'develop','case')['role'],'development')
        for op in ['execute','capture','export']:
            with self.assertRaisesRegex(AdmissionError,'quality_calibration_required'):
                check(admission,op,'case')

    def test_causal_transition_and_old_closure_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);path=root/'ADMISSION.json';admission=self.fixture()
            (root/'input').write_text('frozen')
            admission['files']={str(root/'input'):sha(root/'input')}
            path.write_text(json.dumps(admission))
            with self.assertRaisesRegex(AdmissionError,'causal_transition_required'):
                with claim(path,'develop','case'):pass
            prior=root/'PRIOR.json';prior.write_text(json.dumps(dict(closed=True,scientific_failures=3)))
            transition=dict(prior_method_state=str(prior),prior_method_state_sha256=sha(prior),new_causal_evidence_verified=True,counters_reset=False)
            (root/'METHOD_TRANSITION.json').write_text(json.dumps(transition))
            with claim(path,'develop','case'):pass
            with self.assertRaisesRegex(AdmissionError,'case_already_consumed'):
                with claim(path,'develop','case'):pass
            prior.write_text(json.dumps(dict(closed=False,scientific_failures=0)))
            with self.assertRaisesRegex(AdmissionError,'prior_closure_changed'):
                with claim(path,'develop','case'):pass
