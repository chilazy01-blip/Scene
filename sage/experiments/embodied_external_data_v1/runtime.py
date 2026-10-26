"""Offline CPU setup for the separately accounted data-consumer stage."""
from pathlib import Path
import json
import os
import sys
import time

ROOT = Path('/data/wsj/main/scene')
N = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
Q = N / 'prepared/data_first_20261008'
H = N / 'prepared/hmg_external_control_20261007'


def setup():
    if not 1 <= len(os.sched_getaffinity(0)) <= 8:
        raise RuntimeError('bounded_service_required')
    for name in ('OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'OMP_NUM_THREADS'):
        os.environ[name] = '1'
    for name, folder in [('XDG_CACHE_HOME', 'xdg'), ('MPLCONFIGDIR', 'mpl'),
                         ('NUMBA_CACHE_DIR', 'numba')]:
        path = Q / 'cache' / folder
        path.mkdir(exist_ok=True)
        os.environ[name] = str(path)
    os.environ.update(CUDA_VISIBLE_DEVICES='', MUJOCO_GL='disable',
                      HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1')
    source = json.loads((H / 'FETCH_RESULT_R1.json').read_text())['source_root']
    sys.path[:0] = [str(H / 'vendor'), source, str(ROOT)]


def check_deadline():
    if time.monotonic() > float(os.environ['TASK_DEADLINE_MONOTONIC']) - 3:
        raise TimeoutError('data_consumer_deadline')
    if (Q / 'STOP_REQUESTED').exists():
        raise RuntimeError('data_consumer_stop_requested')
