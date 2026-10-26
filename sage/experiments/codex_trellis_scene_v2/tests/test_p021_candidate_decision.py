from copy import deepcopy
import unittest

from sage.experiments.codex_trellis_scene_v2.p021_candidate_decision import candidate_decisions


class CandidateDecisionTests(unittest.TestCase):
    def setUp(self):
        checks = ['automated_passed','benchmark_passed','AI_visual_passed','coefficient_effect_passed']
        self.protocol = {'schema':'p021-candidate-protocol/v2', 'runs':[
            {'run_id':r, 'method':r, 'comparison_signature_sha256':'frozen'} for r in ('A','B','B0')],
            'candidate_requirements': {m:{'required_control_run_ids':['B0'], 'required_checks':checks,
                'required_control_checks':['automated_passed','AI_visual_passed']} for m in ('A','B')}}
        self.attempts = [{'run_id':r, 'status':'completed', 'comparison_signature_sha256':'frozen',
                          **{c:True for c in checks}} for r in ('A','B','B0')]

    def result(self):
        return candidate_decisions(self.protocol, self.attempts)

    def test_unrelated_terminal_failure_does_not_disqualify_complete_candidate(self):
        self.attempts[1] = {'run_id':'B','status':'failed'}
        result = self.result()
        self.assertTrue(result['candidates']['A']['selectable'])
        self.assertFalse(result['candidates']['B']['eligible'])
        self.assertEqual(result['execution_failures'], ['B'])

    def test_pending_is_not_terminal_failure_and_selection_waits(self):
        self.attempts.pop(1)
        result = self.result()
        self.assertTrue(result['candidates']['A']['eligible'])
        self.assertFalse(result['candidates']['A']['selectable'])
        self.assertFalse(result['selection_ready'])

    def test_required_control_failure_and_missing_visual_review_block(self):
        self.attempts[2]['status']='failed'
        self.assertFalse(self.result()['candidates']['A']['eligible'])
        self.attempts[2]['status']='completed'
        self.attempts[0]['AI_visual_passed']=None
        self.assertFalse(self.result()['candidates']['A']['eligible'])

    def test_changed_unrelated_controls_do_not_poison_own_candidate(self):
        self.attempts[1]['comparison_signature_sha256']='changed'
        self.assertTrue(self.result()['candidates']['A']['eligible'])
        self.assertFalse(self.result()['candidates']['B']['eligible'])

    def test_duplicate_attempts_rejected(self):
        self.attempts.append(deepcopy(self.attempts[0]))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            self.result()
