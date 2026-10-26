"""Regression tests for premature closure, real worker faults and crash recovery."""
import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from . import controller as c


class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bound = self.root / 'input.txt'
        self.bound.write_text('bound test input')
        self.now = time.time()
        self.plan = {
            'limits': {'task_attempts': 20, 'task_physics_steps': 10000, 'service_seconds': 500},
            'initial_spent': {'task_attempts': 8},
            'clock': {'start_epoch': self.now - 100, 'stop_new_work_epoch': self.now + 900,
                      'deadline_epoch': self.now + 1000},
            'working_directory': str(self.root), 'max_job_seconds': 900, 'heartbeat_seconds': 0.05,
            'protected_pools': {'comparison': {'task_attempts': 4}, 'holdout': {'task_attempts': 6}},
            'authorized_scopes': ['engineering', 'reuse'], 'scientific_failure_limit': 3,
            'methods': {'A': {'closed': True, 'scientific_failures': 3},
                        'B': {'closed': True, 'scientific_failures': 2}},
            'jobs': {'analyze': self.job(initial=True)},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, code='pass', initial=False, failure=None, success=None, timeout=2):
        return {'kind': 'planning', 'scope': 'engineering', 'pool': 'development',
                'timeout_seconds': timeout, 'reservation': {'service_seconds': timeout + 5},
                'inputs': {str(self.bound): c.sha(self.bound)}, 'argv': [sys.executable, '-B', '-c', code],
                'initial': initial, 'on_failure': failure or [], 'on_success': success or []}

    def install(self):
        c.write(self.root / 'PLAN.json', self.plan)
        c.write(self.root / 'AUTHORIZATION.json', {'approved': True,
                'plan_sha256': c.sha(self.root / 'PLAN.json'), 'bindings': {str(self.bound): c.sha(self.bound)}})
        self.state = c.initial_state(self.plan)
        c.write(self.root / 'STATE.json', self.state)
        return self.state

    def physical(self, name='transfer', pool='development'):
        job = self.job(initial=True, failure=['analyze'])
        job.update(kind='physics', scope='reuse', pool=pool, method='B', stage='target_robot_transfer')
        job['reservation']['task_attempts'] = 1
        admission = self.root / (name + '_admission.json')
        c.write(admission, {'admitted': True, 'method': 'B', 'scope': 'reuse',
                           'quality_gates_preserved': True, 'inputs': job['inputs'],
                           'controller_frozen': True, 'production_admitted': True, 'fresh_cases': True})
        job['admission'] = {str(admission): c.sha(admission)}
        self.plan['jobs'] = {name: job, 'analyze': self.job()}
        return job

    def test_both_closed_still_dispatch_analysis_and_reject_closure(self):
        self.install()
        self.assertEqual(c.inspect(self.root)['action'], 'dispatch')
        with self.assertRaises(c.AdmissionError):
            c.close(self.root, 'both_branches_closed')
        self.assertFalse((self.root / 'CLOSURE.json').exists())

    def test_empty_queue_requires_replanning(self):
        state = self.install()
        state['jobs']['analyze']['status'] = 'succeeded'
        c.write(self.root / 'STATE.json', state)
        self.assertEqual(c.inspect(self.root)['action'], 'replan')
        with self.assertRaises(c.AdmissionError):
            c.close(self.root, 'no_work')

    def test_third_transfer_allowed_for_active_method_with_shared_development_budget(self):
        self.physical()
        self.plan['methods']['B']['closed'] = False
        state = self.install()
        state['stage_counts']['target_robot_transfer'] = 2
        self.assertEqual(c.decide(self.plan, state, self.now)['job'], 'transfer')

    def test_closed_method_cannot_be_reopened_by_allocation(self):
        self.physical()
        state = self.install()
        self.assertIn('method_closed', c.job_blockers(self.plan, state, 'transfer', self.now))
        self.assertEqual(c.decide(self.plan, state, self.now)['action'], 'replan')

    def test_renamed_method_requires_its_own_admission(self):
        job = self.physical()
        job['method'] = 'B_renamed'
        state = self.install()
        blockers = c.job_blockers(self.plan, state, 'transfer', self.now)
        self.assertIn('method_closed', blockers)
        self.assertIn('physical_contract_mismatch', blockers)

    def test_failure_three_closes_method_activates_analysis(self):
        job = self.physical()
        self.plan['methods']['B']['closed'] = False
        state = self.install()
        c.record_result(self.plan, state, 'transfer', 'scientific_failure', job['reservation'], {}, self.now)
        self.assertTrue(state['methods']['B']['closed'])
        self.assertEqual(state['methods']['B']['scientific_failures'], 3)
        self.assertEqual(c.decide(self.plan, state, self.now)['job'], 'analyze')

    def test_engineering_error_does_not_increment_scientific_count(self):
        state = self.install()
        c.record_result(self.plan, state, 'analyze', 'engineering_failure', {'service_seconds': 1}, {}, self.now)
        self.assertEqual(state['methods']['A']['scientific_failures'], 3)
        self.assertEqual(state['methods']['B']['scientific_failures'], 2)
        self.assertEqual(state['spent']['service_seconds'], 1)

    def test_development_cannot_borrow_frozen_test_slots(self):
        self.physical()
        self.plan['methods']['B']['closed'] = False
        self.plan['initial_spent']['task_attempts'] = 10
        state = self.install()
        self.assertIn('budget:task_attempts', c.job_blockers(self.plan, state, 'transfer', self.now))
        state['jobs']['analyze']['status'] = 'pending'
        self.assertEqual(c.decide(self.plan, state, self.now)['job'], 'analyze')

    def test_holdout_requires_frozen_controller_and_production_admission(self):
        job = self.physical(pool='holdout')
        self.plan['methods']['B']['closed'] = False
        path = Path(next(iter(job['admission'])))
        admission = c.read(path)
        admission.update(controller_frozen=False, production_admitted=False)
        c.write(path, admission)
        job['admission'][str(path)] = c.sha(path)
        state = self.install()
        blockers = c.job_blockers(self.plan, state, 'transfer', self.now)
        self.assertIn('controller_not_frozen', blockers)
        self.assertIn('production_admission_missing', blockers)

    def test_holdout_first_failure_closes_method_without_replacement(self):
        job = self.physical(pool='holdout')
        self.plan['methods']['B'].update(closed=False, scientific_failures=0)
        state = self.install()
        c.record_result(self.plan, state, 'transfer', 'scientific_failure', job['reservation'], {}, self.now)
        self.assertTrue(state['methods']['B']['closed'])
        self.assertEqual(state['methods']['B']['scientific_failures'], 1)

    def test_physics_budget_exhaustion_still_allows_zero_physics_work(self):
        self.plan['protected_pools'] = {}
        self.plan['initial_spent']['task_attempts'] = 20
        state = self.install()
        self.assertEqual(c.decide(self.plan, state, self.now)['action'], 'dispatch')

    def test_deadline_and_seal_window_are_distinct(self):
        state = self.install()
        self.assertEqual(c.decide(self.plan, state, self.now + 950)['action'], 'seal_window')
        decision = c.decide(self.plan, state, self.now + 1000)
        self.assertEqual((decision['action'], decision['reason']), ('stop', 'deadline'))

    def test_unproven_external_blocker_cannot_end_run(self):
        state = self.install()
        state['jobs']['analyze']['status'] = 'dormant'
        state['external_blocker'] = {'external': True, 'requires_user_or_external_change': True,
                                     'authorized_alternatives_exhausted': True, 'covers_jobs': ['analyze']}
        self.assertEqual(c.decide(self.plan, state, self.now)['action'], 'replan')

    def test_real_dependency_failure_repair_and_retry_without_closure(self):
        marker = self.root / 'dependency_fixed'
        self.plan['jobs'] = {
            'bad': self.job("import unavailable_dependency_for_regression", True, ['repair']),
            'repair': self.job(f"from pathlib import Path; Path({str(marker)!r}).write_text('fixed')", success=['retry']),
            'retry': self.job(f"from pathlib import Path; assert Path({str(marker)!r}).read_text() == 'fixed'"),
        }
        self.install()
        self.assertEqual(c.run_one(self.root)['job'], 'repair')
        self.assertEqual(c.run_one(self.root)['job'], 'retry')
        self.assertEqual(c.run_one(self.root)['action'], 'replan')
        state = c.read(self.root / 'STATE.json')
        self.assertEqual(state['jobs']['bad']['outcome'], 'engineering_failure')
        self.assertEqual(state['jobs']['retry']['status'], 'succeeded')
        self.assertEqual(state['methods']['B']['scientific_failures'], 2)
        self.assertGreater(state['spent']['service_seconds'], 0)
        self.assertFalse((self.root / 'CLOSURE.json').exists())

    def test_real_timeout_kills_descendants_and_dispatches_diagnosis(self):
        late = self.root / 'escaped_descendant'
        child = f"import time; from pathlib import Path; time.sleep(.6); Path({str(late)!r}).touch()"
        code = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(5)"
        self.plan['jobs'] = {'slow': self.job(code, True, ['diagnose'], timeout=0.2),
                             'diagnose': self.job()}
        self.install()
        self.assertEqual(c.run_one(self.root)['job'], 'diagnose')
        state = c.read(self.root / 'STATE.json')
        self.assertEqual(state['jobs']['slow']['outcome'], 'timeout')
        time.sleep(0.7)
        self.assertFalse(late.exists())
        self.assertEqual(state['methods']['B']['scientific_failures'], 2)

    def test_recovery_charges_full_reservation_keeps_clock_and_activates_successor(self):
        self.plan['jobs'] = {'lost': self.job(initial=True, failure=['analyze']), 'analyze': self.job()}
        state = self.install()
        state['active'] = {'job': 'lost', 'deadline_epoch': self.now - 20,
                           'reservation': self.plan['jobs']['lost']['reservation']}
        state['jobs']['lost']['status'] = 'running'
        c.write(self.root / 'STATE.json', state)
        self.assertTrue(c.recover(self.root))
        self.assertFalse(c.recover(self.root))
        state = c.read(self.root / 'STATE.json')
        self.assertEqual(state['spent']['service_seconds'], 7)
        self.assertEqual(c.inspect(self.root)['job'], 'analyze')
        self.assertEqual(c.read(self.root / 'PLAN.json')['clock'], self.plan['clock'])

    def test_queue_extension_keeps_spend_methods_and_original_clock(self):
        self.install()
        self.assertEqual(c.run_one(self.root)['action'], 'replan')
        old = c.read(self.root / 'STATE.json')
        report = c.extend_jobs(self.root, {'followup': self.job(initial=True)}, 'Evidence-backed engineering successor')
        new = c.read(self.root / 'STATE.json')
        self.assertEqual(report['job'], 'followup')
        self.assertEqual(old['spent'], new['spent'])
        self.assertEqual(old['methods'], new['methods'])
        self.assertEqual(c.read(self.root / 'PLAN.json')['clock'], self.plan['clock'])
        with self.assertRaises(c.AdmissionError):
            c.extend_jobs(self.root, {'analyze': self.job()}, 'rename existing attempt')

    def test_active_worker_prevents_second_dispatch_or_closure(self):
        state = self.install()
        state['active'] = {'job': 'analyze', 'reservation': {'service_seconds': 7}}
        c.write(self.root / 'STATE.json', state)
        self.assertEqual(c.decide(self.plan, state, self.now)['action'], 'await_worker')
        with self.assertRaises(c.AdmissionError):
            c.close(self.root, 'deadline')

    def test_mutated_authority_rejected_before_command(self):
        self.install()
        self.bound.write_text('changed')
        with self.assertRaises(c.AdmissionError):
            c.run_one(self.root)
        self.assertFalse((self.root / 'jobs').exists())

    def test_nonfinite_or_negative_cost_rejected(self):
        for value in [-1, float('nan'), float('inf')]:
            plan = copy.deepcopy(self.plan)
            plan['initial_spent']['task_attempts'] = value
            with self.assertRaises(c.AdmissionError):
                c.initial_state(plan)


if __name__ == '__main__':
    unittest.main()
