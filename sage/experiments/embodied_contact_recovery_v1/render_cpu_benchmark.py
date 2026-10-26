"""Paired render profile probe against immutable reference pixels."""
import os
import sys
import time
import resource
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E, c, finish

threads = int(sys.argv[1])
assert threads in [4, 8]
assert os.environ['LP_NUM_THREADS'] == str(threads)
assert len(os.sched_getaffinity(0)) == threads
assert resource.getrlimit(resource.RLIMIT_AS)[1] == int(11 * 1024**3)
work = Path(os.environ['CONTINUOUS_JOB_DIR'])
source = E / 'jobs/C_development_03/episode'
reference = E / 'jobs/C3_RGBD_shard_0000/shard.h5'
m = mujoco.MjModel.from_binary_path(str(source / 'MODEL.mjb'))
d = mujoco.MjData(m)
renderer = mujoco.Renderer(m, 256, 256)
usage, rows = {'render_passes': 0}, []
try:
    with h5py.File(source / 'TRACE.h5', 'r') as trace, h5py.File(reference, 'r') as saved:
        for frame in [0, 12, 24, 48, 72, 96, 120, 144, 168, 192, 216, 249]:
            row = int(saved['source_substep_indices'][frame])
            mujoco.mj_setState(m, d, trace['substep/integration_before'][row], mujoco.mjtState.mjSTATE_INTEGRATION)
            mujoco.mj_forward(m, d)
            for camera in ['overhead', 'wrist_cam']:
                renderer.disable_depth_rendering(); renderer.update_scene(d, camera=camera)
                start = time.monotonic(); usage['render_passes'] += 1
                rgb = renderer.render().copy(); rgb_seconds = time.monotonic() - start
                renderer.enable_depth_rendering(); start = time.monotonic(); usage['render_passes'] += 1
                depth = renderer.render().copy(); depth_seconds = time.monotonic() - start
                rgb_error = int(np.max(abs(rgb.astype(int) - saved['cameras/' + camera + '/rgb'][frame].astype(int))))
                depth_error = float(np.max(abs(depth - saved['cameras/' + camera + '/depth_m'][frame])))
                rows.append({'frame': frame, 'camera': camera, 'RGB_error': rgb_error,
                             'depth_error_m': depth_error, 'RGB_seconds': rgb_seconds, 'depth_seconds': depth_seconds})
                c.write(work / 'USAGE.json', usage)
finally:
    renderer.close()
report = {'threads': threads, 'CPU_affinity': sorted(os.sched_getaffinity(0)),
          'address_space_hard_bytes': resource.getrlimit(resource.RLIMIT_AS)[1], 'rows': rows,
          'pixels_identical': all(r['RGB_error'] == 0 and r['depth_error_m'] == 0. for r in rows),
          'warm_mean_seconds_per_pass': float(np.mean([(r['RGB_seconds'] + r['depth_seconds']) / 2 for r in rows[2:]])),
          'source_reference_sha256': c.sha(reference), 'new_physics_steps': 0,
          'unchanged_render_specification': True, 'production_accepted': False}
c.write(work / 'RENDER_BENCHMARK.json', report); finish(report, usage)
