"""Opt-in serial8CPU rendering inside the already authorized aggregate8CPU cap.

All dispatch, locks, hard accounting, physics gates, timeout and memory handling
remain the immutable v3 controller's implementation. Only explicitly tagged
zero-physics rendering/benchmark jobs can use this execution profile.
"""
import json
import os
import resource
import sys
from pathlib import Path
from sage.experiments.embodied_continuous_v3 import controller as base

PROFILE = 'serial_eight_cpu_render_v1'


def eligible(job):
    return (job.get('execution_profile') == PROFILE
            and job['kind'] in ['engineering', 'export']
            and all(job['reservation'].get(name, 0) == 0 for name in
                    ['task_attempts', 'task_physics_steps', 'diagnostic_physics_steps', 'wbc_forwards', 'training_updates'])
            and job.get('render_only') is True
            and job['reservation'].get('render_passes', 0) > 0)


def render_child_limits():
    cpus = sorted(os.sched_getaffinity(0))[:8]
    assert len(cpus) == 8, 'eight_available_CPUs_required'
    os.sched_setaffinity(0, cpus)
    memory = int(11 * 1024**3)
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run(root):
    original = base.job_blockers
    def blockers(plan, state, key, now):
        result = original(plan, state, key, now)
        if not eligible(plan['jobs'][key]):
            result.append('not_a_serial8CPU_render_job')
        return result
    base.job_blockers = blockers
    base.child_limits = render_child_limits
    result = base.run_one(Path(root))
    while result['action'] == 'dispatch':
        result = base.run_one(Path(root))
    print(json.dumps({'execution_profile': PROFILE, 'result': result}, ensure_ascii=False))
    return 75 if result.get('action') == 'replan' else 0


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1]))
