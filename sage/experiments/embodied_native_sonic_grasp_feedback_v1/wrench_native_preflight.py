"""Test actual-contact wrench/motor feasibility at the validated loaded grasp."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .posture_screen import load_model
from .feedback import allocate
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_native_sonic_grasp_diagnosis_v1.friction import load_after

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);episode=root/'attempt_15/full';r=read_bound_json(episode/'REPORT.json');t=read_bound_json(episode/'TRACE.json');m=load_model(r['model']['path']);d=mujoco.MjData(m);weight=float(m.body_mass[m.body('payload').id]*9.81);out=[]
    for tick in [1361,1380,1400,1420,1430,1450]:
        s=t['records'][tick]['substeps'][-1];load_after(mujoco,m,d,s)
        for minimum in [.5,.75,1.]:
            result=allocate(mujoco,m,d,dict(thumb=1.5,index=minimum,middle=1.5),[0,0,weight,0,0,0]);out.append(dict(tick=tick,index_minimum_n=minimum,actual_group_normals_n=s['forces'],allocation=result))
    initial=next(x for x in out if x['tick']==1361 and x['index_minimum_n']==.75);safe_save(root/'NATIVE_WRENCH_PREFLIGHT.json',dict(new_physics_steps=0,initial_loaded_wrench_feasible=initial['allocation']['feasible'],rows=out,report=_file_binding(episode/'REPORT.json'),trace=r['trace'],implementation=_file_binding(Path(__file__)),limitation='Instantaneous native contact geometry, actual dry friction/passive/inertia and original motor/reference bounds. No new physics or changed gains/limits. Feasibility does not establish force tracking or successful carrying.'));print(dict(initial_feasible=initial['allocation']['feasible'],rows=[dict(tick=x['tick'],minimum=x['index_minimum_n'],feasible=x['allocation']['feasible']) for x in out]),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
