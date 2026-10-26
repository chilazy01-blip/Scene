"""Zero-integration exact checkpoint and loaded reference slew preview."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol_smooth import authorize,read_bound_json,safe_save,_file_binding
from .task_smooth import Task
from .wrist_smooth import SmoothReference
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);t=read_bound_json(root/'smooth_reference_prefix/TRACE.json');r=read_bound_json(root/'attempt_18/full/REPORT.json');c=read_bound_json(Path(p['case']['path']));m=load_model(r['model']['path']);d=mujoco.MjData(m);base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,base['q'],base['v']);actions=np.zeros((2500,29),np.float32)
    info=restore(mujoco,m,d,task,t,actions,lambda:None,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES));assert info['prefix_physics_steps']==5040
    q=d.qpos.copy();v=d.qvel.copy();N=p['prefix_active_ticks'];oldp=task.feedback.position.copy();oldr=task.feedback.rotation.copy();last=t['records'][-1]['substeps'][-1]
    task.update(N,d,last);task.synchronize(N,d)
    assert task.stage=='loaded_hover' and not task.failure and isinstance(task.feedback,SmoothReference)
    assert np.array_equal(task.feedback.position,oldp) and np.array_equal(task.feedback.rotation,oldr)
    a=task.reference_blocks(N,d,t['initial_qpos'][3:7]);task.synchronize(N+1,d);b=task.reference_blocks(N+1,d,t['initial_qpos'][3:7])
    dp=float(np.linalg.norm(task.feedback.position-oldp));dr=float(np.linalg.norm(task.feedback.rotation-oldr))
    assert dp<=.020*.02+1e-12 and dr<=.120*.02+1e-12
    assert np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v)
    safe_save(root/'SMOOTH_RESTORE_CHECK.json',dict(passed=True,new_physics_steps=0,info=info,loaded_hover_tick=N,first_bias_change_m=0.,first_rotation_bias_change_rad=0.,next20ms_bias_change_m=dp,next20ms_rotation_bias_change_rad=dr,maximum_next_VR_point_change_m=float(np.max(np.linalg.norm((np.asarray(b['vr_3point_local_target'])-a['vr_3point_local_target']).reshape(3,3),axis=1))),physical_state_unchanged=True,original_hover_gate_not_bypassed=True,protocol=_file_binding(root/'SMOOTH_REFERENCE_PROTOCOL.json'),implementation=_file_binding(Path(__file__)),limitation='Two same-state logical reference updates only; no physics, actual new hover or walking success is claimed.'))
    print(dict(passed=True,new_physics_steps=0,reference20ms_bias_step=dp,**info),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
