"""Zero-integration restore and first-close reference preview; never a rollout."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .task_equilibrium import Task
from .posture_screen import load_model,hand_ids
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);check=read_bound_json(root/'EQUILIBRIUM_PLAN_CHECK.json');assert check['passed'];c=read_bound_json(root/'CASE_EQUILIBRIUM_PREVIEW.json');r=read_bound_json(root/'attempt_09/full/REPORT.json');t=read_bound_json(root/'attempt_09/full/TRACE.json');t['records']=t['records'][:980];m=load_model(r['model']['path']);d=mujoco.MjData(m)
    from .protocol_preserved import authorize
    p=authorize(root);ref=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,ref['q'],ref['v']);actions=np.zeros((2500,29),dtype=np.float32);info=restore(mujoco,m,d,task,t,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES));assert info['prefix_physics_steps']==3960 and task.stage=='insert' and not task.failure
    q=d.qpos.copy();v=d.qvel.copy();last=t['records'][-1]['substeps'][-1];task.update(980,d,last);assert task.stage=='close';task.update(981,d,last);h=hand_ids(m);first=np.array(task.hand_targets(h['names']));assert np.max(np.abs(first))<=.006+1e-12 and np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v) and not task.failure
    safe_save(root/'EQUILIBRIUM_RESTORE_PREVIEW.json',dict(passed=True,new_physics_steps=0,planning_only=True,info=info,first_close_reference_rad=first.tolist(),maximum_first_reference_delta_rad=float(np.max(np.abs(first))),body_prefix_controller_history_exact=True,physical_state_unchanged=True,case=_file_binding(root/'CASE_EQUILIBRIUM_PREVIEW.json'),plan_check=_file_binding(root/'EQUILIBRIUM_PLAN_CHECK.json'),source_report=_file_binding(root/'attempt_09/full/REPORT.json'),source_trace=r['trace'],implementation=_file_binding(Path(__file__)),limitation='Updates task logic twice at the same restored physical state solely to inspect the first motor reference. No mj_step, admission, dynamic success or cost reservation. Time extension approval and a new frozen case protocol are required before real rollout.'));print(dict(passed=True,**info,first_reference_step=float(np.max(np.abs(first))),no_integrations=True),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
