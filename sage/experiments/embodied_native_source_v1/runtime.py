from pathlib import Path
import hashlib
import json
import os
import resource
import sys
import time

ROOT=Path('/data/wsj/main/scene')
N=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
J=N/'prepared/native_source_20261008'
F=N/'prepared/root_cause_repair_20261008'
H=N/'prepared/hmg_external_control_20261007'
read=lambda p:json.loads(Path(p).read_text())
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def setup():
    assert 1<=len(os.sched_getaffinity(0))<=8
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    for name in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[name]='1'
    for name,folder in [('NUMBA_CACHE_DIR','numba'),('XDG_CACHE_HOME','xdg'),('MPLCONFIGDIR','mpl')]:
        path=J/'cache'/folder;path.mkdir(exist_ok=True);os.environ[name]=str(path)
    os.environ.update(MUJOCO_GL='disable',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    sys.path[:0]=[str(H/'vendor'),read(H/'FETCH_RESULT_R1.json')['source_root'],str(ROOT)]
    auth=read(J/'AUTHORIZATION.json')
    assert auth['proposal_sha256']==digest(J/'APPROVED_PROPOSAL.json')
    assert auth['additional_component_allowance']==2 and auth['user_reply']

def check_deadline():
    if time.monotonic()>float(os.environ['TASK_DEADLINE_MONOTONIC'])-5 or (J/'STOP_REQUESTED').exists():
        raise TimeoutError('native_source_deadline_or_stop')
