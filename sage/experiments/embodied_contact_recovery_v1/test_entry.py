import copy
from pathlib import Path
import tempfile
import time
import unittest

from sage.experiments.embodied_continuous_v1 import controller as c
from . import entry


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.prepared = self.root / 'prepared'
        self.source = self.root / 'source'
        self.output = self.root / 'run'
        self.prepared.mkdir()
        self.source.mkdir()
        self.human = self.root / 'human.txt'
        self.human.write_text('reviewable plan')
        self.limits = {'task_attempts': 20, 'task_physics_steps': 5040000, 'diagnostic_physics_steps': 20000,
                       'wbc_forwards': 2000000, 'render_passes': 1250000, 'training_updates': 0,
                       'service_seconds': 60000, 'download_bytes': 532908978}
        self.spent = dict.fromkeys(self.limits, 0) | {'task_attempts': 8, 'service_seconds': 100}
        self.methods = {'A': {'closed': True, 'scientific_failures': 3},
                        'B': {'closed': True, 'scientific_failures': 2}}
        c.write(self.source / 'PLAN.json', {'limits': self.limits})
        c.write(self.source / 'STATE.json', {'active': None, 'spent': self.spent, 'methods': self.methods})
        c.write(self.source / 'AUTHORIZATION.json', {'approved': True,
                 'plan_sha256': c.sha(self.source / 'PLAN.json')})
        self.proposal = {
            'package_caps_before': self.limits, 'package_caps_proposed': self.limits | {'task_attempts': 26},
            'project_task_cap_proposed': 62, 'additional_development_trials': 6,
            'allocation': {'development_shared': 8, 'frozen_comparison': 4, 'fresh_holdouts': 6},
            'baseline_spent': self.spent,
            'remaining_allocation': {'task_attempts': 18, 'task_physics_steps': 4560000,
                'diagnostic_physics_steps': 12000, 'wbc_forwards': 1800000, 'render_passes': 250000,
                'training_updates': 0, 'service_seconds': 48000, 'download_bytes': 67108864},
            'service_allocation': {'execute_and_independent_replay': 32580, 'other': 15420},
            'inherited_cumulative_base': {'task_attempts': 36},
        }
        self.contract = {
            'source_root': str(self.source), 'working_directory': str(Path(__file__).resolve().parents[3]),
            'code_bindings': {str(Path(entry.__file__)): c.sha(entry.__file__)},
            'before_first_physics': ['Implement and verify physical workers and independent replay accounting.'],
            'render_contract': {'six_fresh_full_episodes': 180000, 'first_research_full_episode': 30000, 'bounded_diagnostics': 40000},
        }
        self.plan = {'human_plan_path': str(self.human), 'inherited_methods': self.methods,
                     'task_allocation': self.proposal['allocation'],
                     'methods_proposed': {'C': {'principle': 'measured support'}, 'D': {'principle': 'pose planning'}},
                     'clock_proposal': {'duration_seconds': 43200, 'seal_reserve_seconds': 1800,
                                        'old_clock_unchanged': {'start_epoch': 1, 'deadline_epoch': 43201}}}
        self.save()
        self.approval = self.root / 'approval.json'

    def save(self):
        c.write(self.prepared / 'RESOURCE_PROPOSAL.json', self.proposal)
        c.write(self.prepared / 'STARTUP_CONTRACT.json', self.contract)
        self.plan.update(human_plan_sha256=c.sha(self.human),
                         resource_proposal_sha256=c.sha(self.prepared / 'RESOURCE_PROPOSAL.json'),
                         startup_contract_sha256=c.sha(self.prepared / 'STARTUP_CONTRACT.json'))
        c.write(self.prepared / 'PLAN.json', self.plan)
        c.write(self.prepared / 'APPROVAL_REQUEST.json', {'approved': False,
                'plan_sha256': c.sha(self.prepared / 'PLAN.json'),
                'resource_proposal_sha256': c.sha(self.prepared / 'RESOURCE_PROPOSAL.json')})

    def approve_fixture(self):
        c.write(self.approval, {'approved': True, 'user_instruction': 'Synthetic test authorization only',
                'plan_sha256': c.sha(self.prepared / 'PLAN.json'),
                'resource_proposal_sha256': c.sha(self.prepared / 'RESOURCE_PROPOSAL.json'),
                'decisions': ['new_method_scope', 'six_additional_development_trials', 'new_twelve_hour_window']})

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_compiles_without_starting_or_authorizing(self):
        runtime = entry.compile_runtime(self.prepared, self.output, 1000)
        self.assertFalse(self.output.exists())
        self.assertFalse(c.read(self.prepared / 'APPROVAL_REQUEST.json')['approved'])
        state = c.initial_state(runtime)
        self.assertEqual(c.decide(runtime, state, 1000)['job'], 'bootstrap')
        self.assertFalse(runtime['methods']['C']['physical_admission'])
        self.assertEqual(runtime['methods']['A']['scientific_failures'], 3)
        self.assertTrue(runtime['methods']['A']['closed'])

    def test_engineering_cost_drift_fits_without_reapproval(self):
        state = c.read(self.source / 'STATE.json')
        state['spent']['service_seconds'] += 100
        c.write(self.source / 'STATE.json', state)
        runtime = entry.compile_runtime(self.prepared, self.output, 1000)
        self.assertEqual(runtime['initial_spent']['service_seconds'], 200)
        self.assertEqual(runtime['limits']['service_seconds'], 48200)

    def test_shortened_window_rejected(self):
        self.plan['clock_proposal']['duration_seconds'] = 3660
        self.save()
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_new_output_inherits_disk_accounting(self):
        self.contract['disk_checks'] = [{'name': 'new_package', 'roots': [str(self.source)],
                                         'cap_bytes': 80 * 1024**3}]
        self.save()
        runtime = entry.compile_runtime(self.prepared, self.output, 1000)
        self.assertEqual(runtime['disk_checks'][0]['roots'], [str(self.source), str(self.output)])
        self.assertEqual(runtime['disk_checks'][1]['cap_bytes'], 64 * 1024**3)
        self.assertEqual(self.contract['disk_checks'][0]['roots'], [str(self.source)])

    def test_insufficient_actual_budget_rejected(self):
        state = c.read(self.source / 'STATE.json')
        state['spent']['service_seconds'] = 13000
        c.write(self.source / 'STATE.json', state)
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_decreased_counter_rejected(self):
        state = c.read(self.source / 'STATE.json')
        state['spent']['task_attempts'] = 7
        c.write(self.source / 'STATE.json', state)
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_missing_cleanup_reserve_rejected(self):
        self.proposal['service_allocation'] = {'execute_and_independent_replay': 32400, 'other': 15600}
        self.save()
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_render_coverage_mismatch_rejected(self):
        self.contract['render_contract']['six_fresh_full_episodes'] = 170000
        self.contract['render_contract']['bounded_diagnostics'] = 50000
        self.save()
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_active_predecessor_rejected(self):
        state = c.read(self.source / 'STATE.json')
        state['active'] = {'job': 'still_running'}
        c.write(self.source / 'STATE.json', state)
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_changed_document_or_plan_rejected(self):
        self.human.write_text('changed')
        with self.assertRaises(c.AdmissionError):
            entry.check(self.prepared)

    def test_pending_request_cannot_start_a_run(self):
        with self.assertRaises(c.AdmissionError):
            entry.start(self.prepared, self.output, self.prepared / 'APPROVAL_REQUEST.json')
        self.assertFalse(self.output.exists())

    def test_start_and_resume_preserve_original_clock_and_ledger(self):
        self.approve_fixture()
        first = entry.start(self.prepared, self.output, self.approval)
        state = c.read(self.output / 'STATE.json')
        state['spent']['service_seconds'] += 7
        c.write(self.output / 'STATE.json', state)
        second = entry.start(self.prepared, self.output, self.approval)
        self.assertTrue(first['started'])
        self.assertTrue(second['resumed'])
        self.assertEqual(first['clock'], second['clock'])
        self.assertEqual(c.read(self.output / 'STATE.json')['spent']['service_seconds'], 107)
        self.assertFalse(c.read(self.source / 'AUTHORIZATION.json')['approved'])

    def test_same_package_cannot_start_twice(self):
        self.approve_fixture()
        entry.start(self.prepared, self.output, self.approval)
        with self.assertRaises(c.AdmissionError):
            entry.start(self.prepared, self.root / 'second_run', self.approval)

    def test_interrupted_start_keeps_clock_and_recovers_transfer(self):
        self.approve_fixture()
        first = entry.start(self.prepared, self.output, self.approval)
        (self.output / 'STARTED.json').unlink()
        restored = entry.start(self.prepared, self.output, self.approval)
        self.assertEqual(restored['clock'], first['clock'])
        self.assertFalse(c.read(self.source / 'AUTHORIZATION.json')['approved'])

    def test_partial_initialization_with_work_cannot_reset_costs(self):
        self.approve_fixture()
        entry.start(self.prepared, self.output, self.approval)
        (self.output / 'STARTED.json').unlink()
        state = c.read(self.output / 'STATE.json')
        state['events'].append({'job': 'work_already_happened'})
        c.write(self.output / 'STATE.json', state)
        with self.assertRaises(c.AdmissionError):
            entry.start(self.prepared, self.output, self.approval)

    def test_real_engineering_bootstrap_returns_worklist_not_parent_success(self):
        self.approve_fixture()
        entry.start(self.prepared, self.output, self.approval)
        decision = c.run_one(self.output)
        self.assertEqual(decision['action'], 'replan')
        worklist = c.read(self.output / 'STARTUP_WORKLIST.json')
        self.assertTrue(worklist['requires_coordinator_work'])
        self.assertFalse(worklist['full_objective_achieved'])
        self.assertFalse((self.output / 'CLOSURE.json').exists())


if __name__ == '__main__':
    unittest.main()
