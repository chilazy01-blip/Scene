"""Preserve worker outcomes even when optional telemetry is unavailable.

The external launcher must reconcile a worker killed without Python cleanup.
Neither a missing counter nor a missing worker terminal implies success.
"""
from pathlib import Path
import json
import os
import runpy
import signal
import sys
import threading
import time
import traceback


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def counters(directory):
    result = {}
    for name in ['cpu.stat', 'io.stat', 'memory.peak', 'memory.current', 'memory.events']:
        try:
            value = (directory / name).read_text().strip()
            result[name] = dict(value=value, available=True, reason=None)
        except (OSError, AttributeError) as exc:
            result[name] = dict(value=None, available=False, reason=type(exc).__name__)
    return result


class Terminated(BaseException):
    pass


def worker(output, script, arguments, gpu=False):
    # Create durable start evidence before resource discovery or admission.
    output = Path(output)
    started = time.monotonic()
    result = dict(status='starting', started_at=time.time(), script=str(script),
                  arguments=arguments, pid=os.getpid(), gpu_requested=gpu)
    write(output / 'started.json', result)
    stop = threading.Event()
    watcher = broker = watchdog = gpu_stop = directory = None
    job = 'scene-learner-validation-' + output.name
    exit_code = 1
    previous = {}
    def terminated(signum, frame):
        raise Terminated(signum)
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, terminated)
    try:
        from sage.experiments.codex_trellis_scene_v2.p021_full_workflow import (
            CPU_ENV, cgroup_directory, guard, lock_inherited_affinity, monitor)
        cpus = set(os.sched_getaffinity(0))
        if not 1 <= len(cpus) <= 8:
            raise ValueError('dedicated_at_most_8_cpu_service_required')
        lock_inherited_affinity()
        if not gpu:
            os.environ.update(CPU_ENV)
        os.environ.update(OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                          OMP_NUM_THREADS=str(len(cpus)), PYTHONDONTWRITEBYTECODE='1')
        directory = cgroup_directory()
        result['initial_counters'] = counters(directory)
        admission = guard(directory, cpus)
        write(output / 'admission.json', admission)
        if not admission['accepted']:
            result['status'] = 'rejected'
            raise RuntimeError('resource_admission_rejected')
        watcher = threading.Thread(target=monitor, args=(directory, output, cpus, stop), daemon=True)
        watcher.start()
        if gpu:
            from dataclasses import asdict
            from sage.experiments.codex_trellis_scene_v2.shared_gpu_execution import (
                GIB, SharedGpuBroker, SharedGpuPolicy, process_identity,
                select_shared_gpu, start_watchdog)
            policy = SharedGpuPolicy(required_peak_gib=12, max_runtime_seconds=900)
            choice = select_shared_gpu(policy, maximum_cgroup_memory_bytes=16*GIB)
            write(output / 'gpu_selection.json', choice)
            if not choice['accepted']:
                result['status'] = 'rejected'
                raise RuntimeError('GPU_admission:' + choice['status'])
            selected = choice['gpu']
            lease = Path('/data/wsj/main/scene_runs/codex_trellis_v2/p019_p021_longrun_20260905_v1/shared_heavy_job_lease.json')
            broker = SharedGpuBroker(lease, policy=policy, selected_gpu=selected,
                evidence_path=output/'gpu_admissions.jsonl', maximum_cgroup_memory_bytes=16*GIB)
            admitted = broker.acquire(job)
            if not admitted['accepted']:
                broker = None
                result['status'] = 'rejected'
                raise RuntimeError('GPU_lease_rejected')
            os.environ.update(CUDA_VISIBLE_DEVICES=selected['uuid'], PHASE_GPU_INDEX=str(selected['gpu_index']))
            watchdog, gpu_stop = start_watchdog(dict(policy=asdict(policy),
                owner_identity=process_identity(os.getpid()), selected_gpu=selected,
                maximum_cgroup_memory_bytes=16*GIB, evidence_path=str(output/'gpu_watchdog.jsonl'),
                lease_path=str(lease)))
            def heartbeat():
                while not stop.wait(10):
                    if not broker.heartbeat(job):
                        os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=heartbeat, daemon=True).start()
        result['status'] = 'running'
        sys.argv = [str(script), *arguments]
        os.environ['ROUND2_RESOURCE_DIR'] = str(output)
        runpy.run_path(str(script), run_name='__main__')
        result['status'] = 'completed'; exit_code = 0
    except SystemExit as exc:
        exit_code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        result.update(status='completed' if exit_code == 0 else 'failed', system_exit=repr(exc.code))
    except Terminated as exc:
        exit_code = 128 + int(exc.args[0])
        result.update(status='interrupted', signal=int(exc.args[0]))
    except BaseException:
        if result['status'] != 'rejected':
            result['status'] = 'failed'
        result['traceback'] = traceback.format_exc()
        print(result['traceback'], flush=True)
    finally:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        stop.set()
        if watcher is not None:
            watcher.join(timeout=6)
        cleanup_errors = []
        try:
            if gpu_stop is not None:
                gpu_stop.set(); watchdog.join(timeout=3)
            if broker is not None:
                result['lease_released'] = broker.release(job)
        except BaseException:
            cleanup_errors.append(traceback.format_exc())
        result.update(exit_code=exit_code, finished_at=time.time(),
                      wall_seconds=time.monotonic()-started,
                      counters=counters(directory), cleanup_errors=cleanup_errors)
        # Counter reads cannot replace the task outcome or prevent terminal writing.
        write(output/'terminal.json', result)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return exit_code
