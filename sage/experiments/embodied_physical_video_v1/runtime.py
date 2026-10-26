"""Bounded six-hour physical-video milestone; old evidence is immutable."""
from pathlib import Path
import hashlib, json, os, resource, sys, time
ROOT=Path('/data/wsj/main/scene')
N=Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4')
K=N/'prepared/physical_video_20261009'
J=N/'prepared/native_source_20261008'
H=N/'prepared/hmg_external_control_20261007'
E=N/'prepared/expert_task_20261007'
read=lambda p:json.loads(Path(p).read_text())
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n');tmp.replace(p)
def setup(render=False):
    assert 1<=len(os.sched_getaffinity(0))<=8
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    for n in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):os.environ[n]='1'
    for n,f in [('NUMBA_CACHE_DIR','numba'),('XDG_CACHE_HOME','xdg'),('MPLCONFIGDIR','mpl')]:
        p=K/'cache'/f;p.mkdir(exist_ok=True);os.environ[n]=str(p)
    os.environ.update(MUJOCO_GL='egl' if render else 'disable',CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    sys.path[:0]=[str(H/'vendor'),read(H/'FETCH_RESULT_R1.json')['source_root'],str(ROOT)]
    assert read(K/'AUTHORIZATION.json')['plan_sha256']==digest(K/'PLAN.json')
def check_deadline():
    if time.monotonic()>float(os.environ['TASK_DEADLINE_MONOTONIC'])-5 or time.time()>read(K/'PLAN.json')['deadline_epoch'] or (K/'STOP_REQUESTED').exists():
        raise TimeoutError('physical_video_deadline_or_stop')
def charge(**delta):
    limits=read(K/'PLAN.json')['experiment_limits']; c=read(K/'COUNTERS.json')
    mapping=dict(diagnostic_transitions='max_diagnostic_transitions',diagnostic_physics_steps='max_diagnostic_physics_steps',task_attempts='max_materially_distinct_task_attempts',task_physics_steps='max_task_physics_steps',wbc_forwards='max_wbc_forwards',render_passes='max_render_passes')
    for k,v in delta.items():
        assert v>=0
        c[k]+=v
        assert c[k]<=limits[mapping[k]],k
    write(K/'COUNTERS.json',c)
