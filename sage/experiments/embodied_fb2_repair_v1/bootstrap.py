"""Pinned offline runtime and bounded process defaults for repair workers."""
from pathlib import Path
import json,os,resource,sys,time

ROOT=Path('/data/wsj/main/scene')
N=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
F=N/'prepared/root_cause_repair_20261008'
H=N/'prepared/hmg_external_control_20261007'
A=N/'prepared/expert_adaptation_20261007'
P=N/'prepared/phase_feedback_20261007'


def setup():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    cpus=sorted(os.sched_getaffinity(0))
    if not 1<=len(cpus)<=8:raise RuntimeError('bounded_service_affinity_required')
    # The managed parent already locks affinity with seccomp; do not reset it.
    for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[key]='1'
    for key,sub in [('NUMBA_CACHE_DIR','numba'),('MPLCONFIGDIR','matplotlib'),('XDG_CACHE_HOME','xdg')]:
        path=F/'cache'/sub;path.mkdir(exist_ok=True);os.environ[key]=str(path)
    os.environ.update(MUJOCO_GL='disable',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    source=Path(json.loads((H/'FETCH_RESULT_R1.json').read_text())['source_root'])
    sys.path[:0]=[str(H/'vendor'),str(source),str(ROOT)]


def check_deadline():
    deadline=float(os.environ.get('TASK_DEADLINE_MONOTONIC','inf'))
    if time.monotonic()>deadline-5 or (F/'STOP_REQUESTED').exists():
        raise TimeoutError('repair_deadline_or_stop')


def clean(x):
    import numpy as np
    if isinstance(x,np.ndarray):return x.tolist()
    if isinstance(x,np.generic):return x.item()
    if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [clean(v) for v in x]
    return x
