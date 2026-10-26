"""Restore the validated hover checkpoint and verify bounded finger activation."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol_steady import authorize
from .task_steady import Task
from .protocol import read_bound_json,safe_save,_file_binding
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8]);p=authorize(root);c=read_bound_json(Path(p['case']['path']));scene=read_bound_json(Path(p['scene']['path']));m=load_model(scene['model']['path']);d=mujoco.MjData(m);ref=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,ref['q'],ref['v']);t=read_bound_json(root/'reserve_prefix/TRACE.json');actions=np.zeros((2500,29),dtype=np.float32);info=restore(mujoco,m,d,task,t,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES));assert info['prefix_physics_steps']==5488 and not task.failure and task.stage=='loaded_hover' and not task.grasp_test_passed and task.index_extra==0.
    q=d.qpos.copy();v=d.qvel.copy();old=task.finger_reference.copy();position,rotation=task.desired(1362);task.update(1362,d,t['records'][-1]['substeps'][-1]);assert task.stage=='tuck' and task.grasp_test_passed and task.index_extra>0;assert np.array_equal(q,d.qpos) and np.array_equal(v,d.qvel);delta=float(np.max(np.abs(task.finger_reference-old)));assert delta<=.006+1e-12;i=hand_ids(m)['names'].index('right_hand_index_0_joint');assert task.finger_reference[i]<=.7;np.testing.assert_allclose(task.desired(1362)[0],position,atol=1e-12,rtol=0);np.testing.assert_allclose(task.path['goal'],position,atol=1e-12,rtol=0);np.testing.assert_allclose(task.path['R'],rotation,atol=1e-12,rtol=0)
    safe_save(root/'STEADY_CARRY_RESTORE_CHECK.json',dict(passed=True,info=info,new_physics_steps=0,original_hover_gate_passed=True,first_extra_index_reference_rad=task.index_extra,maximum_finger_reference_delta_rad=delta,original_index0_halfclosed_cap_rad=.7,protocol=_file_binding(root/'STEADY_CARRY_PROTOCOL.json'),implementation=_file_binding(Path(__file__))));print(dict(passed=True,**info,reference_delta_rad=delta),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
