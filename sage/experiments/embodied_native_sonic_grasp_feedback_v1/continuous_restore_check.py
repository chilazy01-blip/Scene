"""Verify exact load-pass predecessor and a non-jumping zero-step handoff."""
import argparse,resource,os
from pathlib import Path
import numpy as np
from .protocol_continuous import authorize
from .task_continuous import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from .protocol import read_bound_json,safe_save,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);c=read_bound_json(Path(p['case']['path']));scene=read_bound_json(Path(p['scene']['path']));m=load_model(scene['model']['path']);d=mujoco.MjData(m);ref=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,ref['q'],ref['v']);t=read_bound_json(root/'balanced_prefix/TRACE.json');actions=np.zeros((2500,29),dtype=np.float32);info=restore(mujoco,m,d,task,t,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES));assert info['prefix_physics_steps']==4896 and not task.failure and not task.probe_passed
    q=d.qpos.copy();v=d.qvel.copy();pos,R=task.desired(1214);task.update(1214,d,t['records'][-1]['substeps'][-1]);p2,R2=task.desired(1214);assert task.probe_passed and task.stage=='lift';assert np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v);assert np.array_equal(pos,p2) and np.array_equal(R,R2)
    safe_save(root/'CONTINUOUS_RESTORE_CHECK.json',dict(passed=True,info=info,new_physics_steps=0,load_pass_handoff_without_reference_jump=True,loaded_targets_n=task.loaded_balance_targets,protocol=_file_binding(root/'CONTINUOUS_LIFT_PROTOCOL.json'),implementation=_file_binding(Path(__file__))));print(dict(passed=True,**info,loaded_targets=task.loaded_balance_targets),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
