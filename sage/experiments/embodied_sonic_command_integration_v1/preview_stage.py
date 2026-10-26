"""Zero-step exact state/history restore and early tuck reference continuity check."""
import argparse,os,resource
from pathlib import Path
import numpy as np
from .protocol_stage import authorize,read_bound_json,safe_save,_file_binding
from .task_stage import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);t=read_bound_json(root/'stage_hold_prefix/TRACE.json');r=read_bound_json(root/'attempt_18/full/REPORT.json');c=read_bound_json(Path(p['case']['path']));m=load_model(r['model']['path']);d=mujoco.MjData(m);base=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,base['q'],base['v']);actions=np.zeros((2500,29),np.float32)
    info=restore(mujoco,m,d,task,t,actions,lambda:None,np.asarray(DEFAULT_ANGLES),np.asarray(ACTION_SCALES));assert info['prefix_physics_steps']==5240
    q=d.qpos.copy();v=d.qvel.copy();N=p['prefix_active_ticks'];prior,R=task.desired(N);prior=prior.copy();R=R.copy();task.update(N,d,t['records'][-1]['substeps'][-1]);task.synchronize(N,d);after,A=task.desired(N)
    assert task.stage=='tuck' and task.grasp_test_passed and not task.failure
    assert np.array_equal(prior,after) and np.array_equal(R,A)
    assert np.array_equal(task.path['origin'],task.path['goal'])
    assert np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v)
    safe_save(root/'STAGE_RESTORE_CHECK.json',dict(passed=True,new_physics_steps=0,info=info,original_strict_hover_passed=task.grasp_test_passed,tuck_tick=N,desired_before_m=prior.tolist(),desired_after_m=after.tolist(),desired_position_jump_m=0.,desired_orientation_jump_rad=0.,physical_state_unchanged=True,actual_reference_hold_not_reset_to_measured_pose=True,protocol=_file_binding(root/'STAGE_HOLD_PROTOCOL.json'),implementation=_file_binding(Path(__file__)),limitation='Reference/history and same-state logical stage transition only. Dynamic carry remains unverified.'))
    print(dict(passed=True,new_physics_steps=0,tuck_tick=N,reference_jump=0.,**info),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
