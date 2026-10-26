"""Exact safe pre-carry restore and reference-only loaded phase pacing preview."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol_paced import authorize,read_bound_json,safe_save,_file_binding
from .task_paced import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);t=read_bound_json(root/'paced_carry_prefix/TRACE.json');r=read_bound_json(root/'attempt_21/full/REPORT.json');c=read_bound_json(Path(p['case']['path']));m=load_model(r['model']['path']);d=mujoco.MjData(m);base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,base['q'],base['v']);actions=np.zeros((2500,29),np.float32)
    info=restore(mujoco,m,d,task,t,actions,lambda:None,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES));assert info['prefix_physics_steps']==5480
    q=d.qpos.copy();v=d.qvel.copy();N=p['prefix_active_ticks'];point,R=task.desired(N);point=point.copy();R=R.copy();before=len(task.baseq)
    task.update(N,d,t['records'][-1]['substeps'][-1]);task.synchronize(N,d);after,A=task.desired(N)
    assert task.stage=='carry' and task.grasp_test_passed and not task.failure and task.loaded_paced
    assert len(task.baseq)>before and np.allclose(task.baseq[0],base['q'][0]) and np.allclose(task.basev[0],base['v'][0]*.65)
    assert np.allclose(point,after,atol=1e-12,rtol=0) and np.allclose(R,A,atol=1e-12,rtol=0)
    assert np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v)
    safe_save(root/'PACED_RESTORE_CHECK.json',dict(passed=True,new_physics_steps=0,info=info,phase_rate=.65,reference_frames_before=before,reference_frames_after=len(task.baseq),wrist_reference_position_jump_m=float(np.linalg.norm(after-point)),physical_state_unchanged=True,protocol=_file_binding(root/'PACED_CARRY_PROTOCOL.json'),implementation=_file_binding(Path(__file__)),limitation='Reference/history and same-state stage preview only. Slower loaded walking remains dynamically unverified.'))
    print(dict(passed=True,new_physics_steps=0,reference_frames=len(task.baseq),**info),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
