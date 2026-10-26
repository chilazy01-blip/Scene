"""Zero-integration native checkpoint and official loaded-walk input check."""
import argparse,resource,os
from pathlib import Path
import numpy as np
from .protocol_carry import authorize
from .task_carry import Task
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import DEFAULT_ANGLES,ACTION_SCALES
from sage.experiments.embodied_native_sonic_transport_v1.teleop_reference_ordered import LOWER_INDICES
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab
from .protocol import read_bound_json,safe_save,_file_binding

def run(root):
    import mujoco
    resource.setrlimit(resource.RLIMIT_AS,(16*1024**3,16*1024**3));os.sched_setaffinity(0,sorted(os.sched_getaffinity(0))[:8])
    p=authorize(root);c=read_bound_json(Path(p['case']['path']));scene=read_bound_json(Path(p['scene']['path']));m=load_model(scene['model']['path']);d=mujoco.MjData(m);ref=np.load(p['reference']['path'],allow_pickle=False);task=Task(mujoco,m,c,ref['q'],ref['v']);t=read_bound_json(root/'carry_prefix/TRACE.json');actions=np.zeros((2500,29),dtype=np.float32);info=restore(mujoco,m,d,task,t,actions,lambda:None,np.array(DEFAULT_ANGLES),np.array(ACTION_SCALES));assert info['prefix_physics_steps']==5728 and not task.failure and task.grasp_test_passed and task.stage=='tuck'
    q=d.qpos.copy();v=d.qvel.copy();pos,R=task.desired(1422);task.update(1422,d,t['records'][-1]['substeps'][-1]);p2,R2=task.desired(1422);assert task.stage=='carry' and task.path is not None;assert np.array_equal(d.qpos,q) and np.array_equal(d.qvel,v);np.testing.assert_allclose(pos,p2,atol=1e-12,rtol=0);np.testing.assert_allclose(R,R2,atol=1e-12,rtol=0)
    blocks=task.reference_blocks(1422,d,c['initial_robot_qpos'][3:7]);np.testing.assert_array_equal(blocks['encoder_mode_4'],[1.,0.,0.,0.]);future=1422+np.arange(10)*5;expected=reorder_mujoco_to_isaaclab(task.q[future,7:])[:,LOWER_INDICES].reshape(-1);np.testing.assert_array_equal(blocks['motion_joint_positions_lowerbody_10frame_step5'],expected);assert np.ptp(expected.reshape(10,12),axis=0).max()>.01
    safe_save(root/'CARRY_RESTORE_CHECK.json',dict(passed=True,info=info,new_physics_steps=0,grasp_hover_passed=True,handoff_position_jump_m=float(np.max(np.abs(pos-p2))),handoff_rotation_jump=float(np.max(np.abs(R-R2))),official_mode1=True,lower12_original_order_and_changing_walking_reference_verified=True,protocol=_file_binding(root/'CARRY_WRIST_PROTOCOL.json'),implementation=_file_binding(Path(__file__))));print(dict(passed=True,**info),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
