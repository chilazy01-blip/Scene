"""Explicit opt-in P021 scene -> actual mesh physics -> dynamic visual workflow.

Run inside a CPU-affinity and memory-limited user service. This experimental
entrypoint does not infer real material properties or modify legacy defaults.
"""
from __future__ import annotations

import argparse
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import platform
from pathlib import Path
import signal
import shutil
import stat
import subprocess
import sys
import threading
import time
import traceback

CPU_ENV = {
    'CUDA_VISIBLE_DEVICES': '', 'NVIDIA_VISIBLE_DEVICES': 'void',
    'LIBGL_ALWAYS_SOFTWARE': '1', 'GALLIUM_DRIVER': 'llvmpipe',
    'EGL_PLATFORM': 'surfaceless', '__GLX_VENDOR_LIBRARY_NAME': 'mesa',
    '__EGL_VENDOR_LIBRARY_FILENAMES': '/usr/share/glvnd/egl_vendor.d/50_mesa.json',
    'DISPLAY': '', 'OMP_NUM_THREADS': '8', 'OPENBLAS_NUM_THREADS': '1',
    'MKL_NUM_THREADS': '1', 'LP_NUM_THREADS': '8', 'PYTHONDONTWRITEBYTECODE': '1',
}


def bound(path):
    path = Path(path).resolve()
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)


def utc():
    return datetime.now(timezone.utc).isoformat()


def lock_inherited_affinity():
    """Keep inherited masks immutable when a native library resets affinity.

    This Linux x86-64 filter only denies sched_setaffinity (EPERM). Existing
    CPU masks, all other syscalls, and child creation remain unchanged. Install
    before native libraries/threads; children inherit both mask and filter.
    """
    if platform.machine() != 'x86_64' or len(list(Path('/proc/self/task').iterdir())) != 1:
        raise ValueError('Affinity lock requires single-threaded Linux x86-64 startup')
    class Filter(ctypes.Structure):
        _fields_ = [('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]
    class Program(ctypes.Structure):
        _fields_ = [('len',ctypes.c_ushort),('filter',ctypes.POINTER(Filter))]
    # Validate architecture, load syscall number, deny x86-64 affinity mutation.
    instructions = (Filter*7)(Filter(0x20,0,0,4), Filter(0x15,1,0,0xc000003e),
        Filter(0x06,0,0,0x80000000), Filter(0x20,0,0,0),
        Filter(0x15,0,1,203), Filter(0x06,0,0,0x00050000|errno.EPERM),
        Filter(0x06,0,0,0x7fff0000))
    program = Program(len(instructions),instructions)
    libc = ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0) != 0 or libc.prctl(22,2,ctypes.byref(program),0,0) != 0:
        raise OSError(ctypes.get_errno(),'Cannot install inherited affinity lock')
    actual = set(os.sched_getaffinity(0))
    try:
        os.sched_setaffinity(0,actual)
    except PermissionError:
        pass
    else:
        raise RuntimeError('Kernel did not enforce affinity mutation denial')
    return {'mechanism':'inherited_seccomp_sched_setaffinity_EPERM',
        'architecture':'Linux x86_64','installed_before_native_threads':True,
        'actual_cpus':sorted(actual),'same_mask_mutation_probe':'denied_EPERM',
        'cpu_bandwidth_quota_claimed':False}


def cgroup_directory():
    rows = [line[3:] for line in Path('/proc/self/cgroup').read_text().splitlines()
            if line.startswith('0::')]
    if len(rows) != 1 or rows[0] == '/':
        raise ValueError('A dedicated non-root cgroup v2 service is required')
    root = Path('/sys/fs/cgroup')
    directory = root / rows[0].lstrip('/')
    if not directory.resolve().is_relative_to(root) or not directory.is_dir():
        raise ValueError('Invalid cgroup membership')
    return directory


def snapshot(directory):
    values = {'at': utc(), 'cgroup': str(directory)}
    for name in ('memory.high', 'memory.max', 'memory.current', 'memory.peak', 'memory.events', 'pids.max'):
        path = directory / name
        values[name] = path.read_text().strip() if path.exists() else None
    quota = directory / 'cpu.max'
    values['cpu.max'] = quota.read_text().strip() if quota.exists() else None
    values['affinities'] = {}
    for raw in (directory / 'cgroup.procs').read_text().split():
        taskdir = Path('/proc') / raw / 'task'
        try:
            for task in taskdir.iterdir():
                try:
                    values['affinities'][task.name] = sorted(os.sched_getaffinity(int(task.name)))
                except ProcessLookupError:
                    pass
        except FileNotFoundError:
            pass
    values['host_mem_available_bytes'] = next(int(line.split()[1]) * 1024
        for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    return values


def guard(directory, cpus):
    from .resource_health import sample_resource_health
    report = snapshot(directory)
    errors = []
    for key, limit in [('memory.high', 12*2**30), ('memory.max', 16*2**30), ('pids.max', 2048)]:
        value = report[key]
        if not str(value).isdigit() or not 0 < int(value) <= limit:
            errors.append(key + '_invalid')
    if not errors and (int(report['memory.high']) > int(report['memory.max'])
                       or int(report['memory.current']) >= int(report['memory.high'])):
        errors.append('memory_order_or_current_invalid')
    if not report['affinities'] or any(set(v) != cpus for v in report['affinities'].values()):
        errors.append('thread_affinity_mismatch')
    report['resource_health'] = sample_resource_health(sample_seconds=.5)
    if not report['resource_health']['healthy_for_heavy_stage']:
        errors.append('P007_rejected')
    report.update(accepted=not errors, errors=errors, cpu_control='actual_kernel_affinity',
                  cpu_quota_claimed=False)
    return report


def monitor(directory, output, cpus, stop):
    with (output / 'resources.jsonl').open('a', buffering=1) as stream:
        while not stop.is_set():
            try:
                record = snapshot(directory)
                reasons = []
                if int(record['memory.current']) >= 14.5*2**30:
                    reasons.append('own_memory_near_limit')
                if record['host_mem_available_bytes'] < 96*2**30:
                    reasons.append('host_memory_below_P007')
                if any(set(v) != cpus for v in record['affinities'].values()):
                    reasons.append('thread_affinity_widened')
                stream.write(json.dumps(record) + '\n')
                if reasons:
                    write(output / 'resource_stop.json', {'at': utc(), 'reasons': reasons,
                        'snapshot': record, 'scope': 'only this owned service'})
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
            except Exception as exc:
                write(output / 'resource_monitor_error.json', {'at': utc(), 'error': repr(exc)})
                os.kill(os.getpid(), signal.SIGTERM)
                return
            stop.wait(5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--blender', required=True, type=Path)
    parser.add_argument('--cpus', default='0,1,2,3,4,5,6,7')
    parser.add_argument('--resolution', default=640, type=int)
    parser.add_argument('--samples', default=16, type=int)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    stages = []
    stop = threading.Event()
    monitor_thread = None
    try:
        cpus = {int(x) for x in args.cpus.split(',')}
        if not 1 <= len(cpus) <= 8 or not cpus <= set(os.sched_getaffinity(0)):
            raise ValueError('Invalid or expanding CPU affinity')
        os.sched_setaffinity(0, cpus)
        affinity_lock = lock_inherited_affinity()
        xdg = args.output / 'xdg'
        xdg.mkdir(mode=0o700)
        if stat.S_IMODE(xdg.stat().st_mode) != 0o700:
            raise ValueError('Private XDG runtime required')
        os.environ.update(CPU_ENV, XDG_RUNTIME_DIR=str(xdg.resolve()))
        directory = cgroup_directory()
        admission = guard(directory, cpus)
        admission['inherited_affinity_lock'] = affinity_lock
        write(args.output / 'admission.json', admission)
        if not admission['accepted']:
            raise ValueError('Resource admission rejected: ' + repr(admission['errors']))
        from .p021_physics_scene import prepare_scene
        from .p021_physics import run_physics, require_engineering_success
        module_dir = Path(__file__).resolve().parent
        renderer = module_dir.parents[1] / 'scripts' / 'blender_p021_physics_render.py'
        code = [Path(__file__), module_dir/'p021_physics_scene.py', module_dir/'p021_physics.py',
                module_dir/'p021_physics_diagnostics.py', module_dir/'physical_mass.py',
                module_dir/'multilevel_proxy.py', module_dir/'collision_mesh_cleanup.py', renderer]
        snapshots = args.output/'code_snapshot'
        snapshots.mkdir()
        snapshot_bindings = []
        for path in code:
            copy = snapshots/path.name
            shutil.copyfile(path, copy)
            if bound(copy)['sha256'] != bound(path)['sha256']:
                raise ValueError('Code changed during execution snapshot')
            snapshot_bindings.append({'original_path':str(path), **bound(copy)})
        write(args.output / 'execution.json', {'schema': 'p021-full-execution/v1', 'at': utc(),
            'pid': os.getpid(), 'argv': sys.argv, 'spec': bound(args.spec),
            'inventory': bound(args.inventory), 'code': [bound(p) for p in code],
            'code_snapshots':snapshot_bindings,
            'python': sys.executable, 'blender': str(args.blender), 'environment': CPU_ENV})
        monitor_thread = threading.Thread(target=monitor, args=(directory,args.output,cpus,stop), daemon=True)
        monitor_thread.start()

        def stage(name, function):
            start = time.monotonic()
            stage_admission = guard(directory, cpus)
            write(args.output/(name + '_admission.json'), stage_admission)
            if not stage_admission['accepted']:
                raise ValueError('Stage resource admission rejected: ' + repr(stage_admission['errors']))
            write(args.output/'current_stage.json', {'at': utc(), 'stage': name, 'status': 'running'})
            result = function()
            stages.append({'stage': name, 'wall_seconds': time.monotonic()-start, 'status': 'complete'})
            write(args.output/'stage_timings.json', stages)
            return result

        stage('request_source_layout_assembly_geometry', lambda: prepare_scene(
            args.spec, args.output/'scene', args.inventory, args.blender))
        scene = args.output/'scene'/'scene.glb'
        geometry = json.loads((args.output/'scene'/'geometry_qa.json').read_text())
        if geometry.get('accepted') is not True:
            raise ValueError('Final geometry correspondence rejected')
        spec = json.loads(args.spec.read_text())
        spec['scene_glb'] = bound(scene)
        write(args.output/'physics_input.json', spec)
        physics = args.output/'physics'
        physics.mkdir()
        stage('actual_mesh_dynamics', lambda: require_engineering_success(run_physics(scene, spec, physics)))
        renders = args.output/'renders'
        command = [str(args.blender), '-b', '-t', str(len(cpus)), '--python-exit-code', '2', '-P', str(renderer), '--',
            '--scene', str(scene), '--trajectory', str(physics/'trajectory.json'),
            '--binding', str(physics/'physics_binding.json'), '--output-dir', str(renders),
            '--resolution', str(args.resolution), '--samples', str(args.samples)]
        def render():
            with (args.output/'render.stdout.log').open('w') as stdout, (args.output/'render.stderr.log').open('w') as stderr:
                subprocess.run(command, stdout=stdout, stderr=stderr, check=True, timeout=3600)
            manifest = json.loads((renders/'render_manifest.json').read_text())
            trajectory = json.loads((physics/'trajectory.json').read_text())
            actions = [f for f in trajectory['frames'] if f['phase']=='action']
            diagnostics = trajectory.get('diagnostic_frames', [])
            expected_count = len(actions) + len(diagnostics) + 3
            if (manifest.get('ok') is not True or manifest.get('rendered_png_count') != expected_count
                    or manifest.get('action_frame_count') != len(actions)
                    or manifest.get('diagnostic_frame_count', 0) != len(diagnostics)
                    or len(manifest.get('frames', [])) != expected_count):
                raise ValueError('Actual dynamic render manifest incomplete')
            for frame in manifest['frames']:
                if bound(frame['image']['path']) != frame['image']:
                    raise ValueError('Rendered frame changed or missing')
        stage('actual_dynamic_and_final_rendering', render)
        stop.set(); monitor_thread.join(timeout=6)
        artifacts = [p for p in args.output.rglob('*') if p.is_file() and p.name != 'workflow_result.json']
        result = {'schema': 'p021-full-workflow-result/v1', 'at': utc(),
            'status': 'completed_pending_independent_analysis_and_AI_visual_review',
            'accepted': None, 'stages': stages, 'wall_seconds': time.monotonic()-started,
            'artifacts': [bound(p) for p in sorted(artifacts)], 'resources_final': snapshot(directory),
            'external_physics_validated': False, 'human_review': None, 'new_generation': False}
        write(args.output/'workflow_result.json', result)
        print(json.dumps({'status': result['status'], 'output': str(args.output), 'wall_seconds': result['wall_seconds']}), flush=True)
        return 0
    except Exception:
        stop.set()
        if monitor_thread:
            monitor_thread.join(timeout=6)
        write(args.output/'workflow_failure.json', {'at': utc(), 'stages': stages,
            'wall_seconds': time.monotonic()-started, 'traceback': traceback.format_exc()})
        traceback.print_exc()
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
