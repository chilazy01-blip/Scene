"""The opt-in render profile must preserve aggregate limits and reject physics."""
import unittest
from unittest.mock import patch
from .serial_render_controller import eligible, render_child_limits, PROFILE


class RenderProfileTests(unittest.TestCase):
    def test_only_explicit_zero_physics_render_jobs(self):
        job = {'execution_profile': PROFILE, 'kind': 'engineering', 'render_only': True,
               'reservation': {'render_passes': 48, 'service_seconds': 125}}
        self.assertTrue(eligible(job))
        for key in ['task_attempts', 'task_physics_steps', 'diagnostic_physics_steps', 'wbc_forwards', 'training_updates']:
            changed = {**job, 'reservation': {**job['reservation'], key: 1}}
            self.assertFalse(eligible(changed))
        self.assertFalse(eligible({**job, 'kind': 'physics'}))
        self.assertFalse(eligible({**job, 'execution_profile': 'unapproved'}))
        self.assertFalse(eligible({**job, 'render_only': False}))

    def test_eight_core_and_eleven_gib_hard_limits(self):
        with patch('os.sched_getaffinity', return_value=set(range(10, 26))), \
             patch('os.sched_setaffinity') as affinity, patch('resource.setrlimit') as memory:
            render_child_limits()
            affinity.assert_called_once_with(0, list(range(10, 18)))
            self.assertIn((int(11 * 1024**3), int(11 * 1024**3)), [call.args[1] for call in memory.call_args_list])

    def test_insufficient_cpu_availability_fails(self):
        with patch('os.sched_getaffinity', return_value={0, 1, 2, 3}), patch('os.sched_setaffinity') as affinity:
            with self.assertRaises(AssertionError):
                render_child_limits()
            affinity.assert_not_called()


if __name__ == '__main__':
    unittest.main()
