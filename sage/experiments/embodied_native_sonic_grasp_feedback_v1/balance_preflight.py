"""Test actual load-pass preload deficit without extra integration."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol import read_bound_json,safe_save,_file_binding
from .posture_screen import load_model,hand_ids
from .balanced_preload import solve,ROLES
from .feedback import allocate
from sage.experiments.embodied_native_sonic_transport_v1.restore import load_after
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    ep=root/'attempt_09/full';r=read_bound_json(ep/'REPORT.json');t=read_bound_json(ep/'TRACE.json');c=read_bound_json(Path(r['case']['path']));m=load_model(r['model']['path']);d=mujoco.MjData(m);s=t['records'][1213]['substeps'][-1];load_after(mujoco,m,d,s);rows,info=contacts(mujoco,m,d);fn={g:sum(x['normal_n'] for x in rows if x['role']==g) for g in ROLES};minimum={g:max(1.5,fn[g]) for g in ROLES};z=solve(rows,info['weight_n'],np.array(info['com_m']),minimum);allocation=None;limits=None
    if z['feasible']:
        allocation=allocate(mujoco,m,d,z['group_normals_n'],[0,0,1.5*info['weight_n'],0,0,0])
        if allocation['feasible']:
            h=hand_ids(m);ix=np.array(allocation['right_finger_indices']);ends=np.array([c['mesh_finger_template'][h['names'][i]]*.5 for i in ix]);lo=np.minimum(0,ends);hi=np.maximum(0,ends);tau=np.array(allocation['predicted_required_motor_torque_nm']);lower=h['kp'][ix]*(lo-d.qpos[h['qpos'][ix]])-h['kd']*d.qvel[h['dofs'][ix]];upper=h['kp'][ix]*(hi-d.qpos[h['qpos'][ix]])-h['kd']*d.qvel[h['dofs'][ix]];limits=dict(custom_template_motor_bound_passed=bool(np.all(tau>=lower-1e-8) and np.all(tau<=upper+1e-8)),requested_nm=tau.tolist(),lower_nm=lower.tolist(),upper_nm=upper.tolist())
    out=dict(new_physics_steps=0,actual_load_pass_tick=1214,observed_group_normals_n=fn,proposed_balanced_preload=z,instantaneous_native_allocation=allocation,custom_reference_bounds=limits,report=_file_binding(ep/'REPORT.json'),trace=r['trace'],implementation=_file_binding(Path(__file__)),limitation='Actual-state geometry and instantaneous actuation feasibility, not dynamic proof or a unique cause of lift slip.');safe_save(root/'LOADED_BALANCE_PREFLIGHT.json',out);print(out,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
