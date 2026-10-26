import copy
import unittest
from . import controller as c
from .test_controller import ContinuationTests


class AccountingTests(ContinuationTests):
    def test_closed_method_saved_replay_allowed_zero_tasks(self):
        job = self.job(initial=True, failure=['analyze'])
        job.update(kind='audit', replay={'exact_saved_inputs': True, 'source_method': 'A',
                                       'bindings': job['inputs']})
        job['reservation']['task_physics_steps'] = 100
        self.plan['jobs'] = {'replay': job, 'analyze': self.job()}
        state = self.install()
        self.assertEqual(c.decide(self.plan, state, self.now)['job'], 'replay')
        c.record_result(self.plan, state, 'replay', 'success',
                        {'task_physics_steps': 87, 'service_seconds': 1}, {}, self.now)
        self.assertEqual(state['spent']['task_attempts'], 8)
        self.assertEqual(state['spent']['task_physics_steps'], 87)
        self.assertEqual(state['methods']['A']['scientific_failures'], 3)

    def test_analysis_cannot_hide_physics(self):
        self.plan['jobs']['analyze']['reservation']['task_physics_steps'] = 1
        with self.assertRaises(c.AdmissionError):
            self.install()

    def test_replay_requires_saved_binding(self):
        job = self.job(initial=True, failure=['analyze'])
        job.update(kind='audit')
        self.plan['jobs']['replay'] = job
        state = self.install()
        self.assertIn('saved_replay_binding_missing', c.job_blockers(self.plan, state, 'replay', self.now))

    def test_overrun_rejected_atomically(self):
        state = self.install()
        old = copy.deepcopy(state)
        with self.assertRaises(c.AdmissionError):
            c.record_result(self.plan, state, 'analyze', 'success',
                            {'service_seconds': 1, 'task_physics_steps': 1}, {}, self.now)
        self.assertEqual(state, old)

    def test_bound_actual_receipt_and_crash_fallback(self):
        job = self.job()
        job['reservation']['task_physics_steps'] = 100
        c.write(self.root / 'REQUEST.json', job)
        c.write(self.root / 'USAGE_FINAL.json', {'complete': True,
                'request_sha256': c.sha(self.root / 'REQUEST.json'),
                'usage': {'task_physics_steps': 34}})
        actual, _ = c.measured_usage(self.root, job, 0.2, True)
        self.assertEqual(actual['task_physics_steps'], 34)
        actual, _ = c.measured_usage(self.root, job, 0.2, False)
        self.assertEqual(actual['task_physics_steps'], 100)
        c.write(self.root / 'REQUEST.json', {})
        actual, _ = c.measured_usage(self.root, job, 0.2, True)
        self.assertEqual(actual['task_physics_steps'], 100)


if __name__ == '__main__':
    unittest.main()
