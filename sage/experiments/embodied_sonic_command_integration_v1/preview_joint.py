"""Actual state check of initial preserved-preload native6D joint feedback."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol_joint import authorize,read_bound_json,safe_save,_file_binding
from .task_joint import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);t=read_bound_json(root/'contact_torque_prefix/TRACE.json');r=read_bound_json(root/'attempt_21/full/REPORT.json');c=read_bound_json(Path(p['case']['path']));m=load_model(r['model']['path']);m.opt.timestep=.005;d=mujoco.MjData(m);base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,base['q'],base['v']);actions=np.zeros((2500,29),np.float32)
    info=restore(mujoco,m,d,task,t,actions,lambda:None,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES));assert info['prefix_physics_steps']==5244
    q=d.qpos.copy();v=d.qvel.copy();anchor=task.anchor.copy();h=hand_ids(m);old=np.asarray(task.hand_targets(h['names']));N=p['prefix_active_ticks']
    task.update(N,d,t['records'][-1]['substeps'][-1]);task.synchronize(N,d);new=np.asarray(task.hand_targets(h['names']))
    assert task.stage=='tuck' and task.grasp_test_passed and not task.failure
    assert task.feedback_allocation['feasible'] and max(abs(new-old))<=.006+1e-12
    assert np.array_equal(task.anchor,anchor) and np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v)
    safe_save(root/'CONTACT_RESTORE_CHECK.json',dict(passed=True,new_physics_steps=0,info=info,first_tracking_tick=N,minimum_normals_n=task.contact_minimum,initial_actual_native_allocation=task.feedback_allocation,maximum_first_reference_delta_rad=float(max(abs(new-old))),original_acceptance_anchor_unchanged=True,physical_state_unchanged=True,protocol=_file_binding(root/'CONTACT_TORQUE_PROTOCOL.json'),implementation=_file_binding(Path(__file__)),limitation='Same-state instantaneous feasibility and first bounded reference update only, not dynamic force realization.'))
    print(dict(passed=True,new_physics_steps=0,initial_LP=True,maximum_first_delta=float(max(abs(new-old))),**info),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
