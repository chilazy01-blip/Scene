import argparse,os,resource
from pathlib import Path
import numpy as np
from .allocation import solve
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'version_01/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');c=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);out=[]
    for tick in [1150,1195,1200,1230,1265,1340]:
        s=t['records'][tick-1]['substeps'][-1];load_after(mujoco,m,d,s);a=solve(mujoco,m,d,c['loaded_preload_targets_n']);out.append(dict(tick=tick,allocation=a));print(out[-1],flush=True)
    safe_save(root/'ALLOCATION_PREFLIGHT.json',dict(new_physics_steps=0,actual_state_count=len(out),feasible_count=sum(x['allocation']['feasible'] for x in out),rows=out,source_trace=r['trace'],implementation=_file_binding(Path(__file__)),allocation_implementation=_file_binding(Path(__file__).with_name('allocation.py'))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);run(p.parse_args().root)
