"""Verify new task preserves exact safe prefix and current native finger limits."""
import argparse,resource,os
from pathlib import Path
import numpy as np
from .protocol_top import authorize
from .task_top import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.protocol import read_bound_json,safe_save,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);c=read_bound_json(Path(p['case']['path']));scene=read_bound_json(Path(p['scene']['path']));model=load_model(scene['model']['path']);d=mujoco.MjData(model);ref=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,model,c,ref['q'],ref['v']);t=read_bound_json(root/'top_prefix/TRACE.json');a=np.zeros((2000,29),dtype=np.float32);info=restore(mujoco,model,d,task,t,a,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES));assert info['prefix_physics_steps']==3200 and not task.failure
    safe_save(root/'TOP_RESTORE_CHECK.json',dict(passed=True,info=info,new_physics_steps=0,protocol=_file_binding(root/'TOP_PROTOCOL.json'),implementation=_file_binding(Path(__file__))));print(dict(passed=True,**info),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
