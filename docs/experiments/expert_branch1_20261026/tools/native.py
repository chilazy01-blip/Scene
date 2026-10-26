"""Reproducible declared existing CPU/engine environment, never install."""
import os,sys,subprocess,resource
resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
P='/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1'
env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MUJOCO_GL='egl',PYTHONPATH='/data/wsj/main/scene:'+P+'/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009/native_parallel_12h_20261011/shared/env37')
sys.exit(subprocess.call([P+'/cpu_env/bin/python','-B',*sys.argv[1:]],env=env,cwd='/data/wsj/main/scene'))
