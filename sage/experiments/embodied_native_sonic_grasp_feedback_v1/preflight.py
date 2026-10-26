import argparse,os,resource
from pathlib import Path
import numpy as np
from .feedback import allocate,advance
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_sonic_grasp_v1.protocol import check
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import read_bound_json
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import _file_binding

def run(root,parent):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=read_bound_json(parent/'FINAL_REVIEW.json')
    for b in p['sources'].values():check(b)
    r=read_bound_json(parent/'version_01/full/REPORT.json');case=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);out=[]
    for version,tick in [(1,1194),(2,1200),(2,1260)]:
        t=read_bound_json(parent/('version_0%d/full/TRACE.json'%version));s=t['records'][tick-1]['substeps'][-1];load_after(mujoco,m,d,s);weight=m.body_mass[m.body('payload').id]*9.81
        for fraction in [.8,1.]:
            z=allocate(mujoco,m,d,case['loaded_preload_targets_n'],[0,0,fraction*weight,0,0,0]);assert z['feasible'],(version,tick,fraction,z);assert z['equilibrium_error']<1e-9;out.append(dict(version=version,tick=tick,weight_fraction=fraction,allocation=z))
    safe_save(root/'PREFLIGHT.json',dict(passed=True,new_physics_steps=0,rows=out,implementation=_file_binding(Path(__file__)),feedback=_file_binding(Path(__file__).with_name('feedback.py')),limitation='Actual contact/dry friction/dynamic accounting and feedback-law checks; actual load transfer and full task require dynamic verification.'))
    print(dict(passed=True,states=3,wrench_checks=6,new_physics_steps=0),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--parent',type=Path,required=True);a=p.parse_args();run(a.root,a.parent)
