import argparse,os,resource
from pathlib import Path


def main():
    os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MUJOCO_GL='egl')
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['preview','engine','measure','feedback','audit','force','replay','render','delivery']);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root;episode=root/'full'
    if a.action=='preview':
        from .preview import run
        run(root)
    elif a.action=='engine':
        from .engine import run
        import mujoco
        from . import guard
        from .common import safe_save,read_bound_json,_file_binding
        native_step=mujoco.mj_step;calls=0
        def counted_step(*args,**kwargs):
            nonlocal calls
            if guard.EXPERT_ACTIVE:raise RuntimeError('expert attempted direct unaccounted integration')
            calls+=1
            return native_step(*args,**kwargs)
        mujoco.mj_step=counted_step
        try:run(root,episode,3200)
        finally:
            mujoco.mj_step=native_step
            cost=root/'cost/REPORT.json'
            if not cost.exists():
                cost.parent.mkdir(exist_ok=True)
                safe_save(cost,dict(physics_steps=calls,native_integrator_calls=calls,engineering_failure_before_normal_report=True,
                                   accounting_only=True,implementation=_file_binding(Path(__file__))))
            else:assert read_bound_json(cost)['physics_steps']==calls
            safe_save(root/'NATIVE_CALL_COUNT.json',dict(native_integrator_calls=calls,implementation=_file_binding(Path(__file__))))
    elif a.action=='measure':
        from .review import measure
        measure(root)
    elif a.action=='feedback':
        from .feedback_v2 import build
        build(root)
    elif a.action=='audit':
        from .audit import audit
        audit(root,episode)
    elif a.action=='force':
        from .force import run
        run(episode)
    elif a.action=='replay':
        from .replay_numerical_v2 import run
        run(root,episode,root/'continuous_replay')
    elif a.action=='render':
        from .visualize_v3 import run
        run(root,root/'actual_video_v3',episode)
    else:
        from .delivery_v4 import run
        dyn=root/'continuous_replay'
        run(root,episode,root/'actual_video_v3',dyn if dyn.exists() else None)


if __name__=='__main__':main()
