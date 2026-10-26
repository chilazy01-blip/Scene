"""Check new grasp planner on the measured prior full-task acquisition state."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish

def main(config):
 cfg=c.read(config);work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
 from .target_adapter_r4 import install
 install('A','gain_translation',work/'static_interface')
 import run
 from ik.sim import ArmIK6
 from .planned_tripod_world_offset import plan,FINGER_NAMES
 from .tripod_clearance_arc_r3 import plan_arc
 source=E/'jobs'/cfg['source_job'];folder=source/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl)
 old=c.read(source/'D_MEASURED_TRIPOD_PLAN.json');fa=np.array([m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in FINGER_NAMES]);ids=np.r_[ik.qpos_idx,fa];target=np.r_[old['initial_arm_rad'],old['initial_finger_rad']]
 with h5py.File(folder/'TRACE.h5','r') as f:
  q=f['substep/qpos'][:];errors=np.max(abs(q[:,ids]-target),axis=1);row=int(np.argmin(errors));d.qpos[:]=q[row]
 d.qpos[m.jnt_qposadr[m.joint('left_elbow_joint').id]]+=cfg['left_elbow_additional_offset_rad'];mujoco.mj_forward(m,d)
 class Runner:
  model=m;data=d;cyl_bid=m.body('red_block').id
  def __init__(self):self.ik=ik
  def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
  def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
 r=Runner();grasp=plan(r,c.read(cfg['template'])['selected']);arc=plan_arc(r,grasp) if grasp.get('valid') else None
 report={'passed':bool(grasp.get('valid') and arc and arc['valid']),'saved_source_row':row,'saved_joint_match_max_error_rad':float(errors[row]),'grasp':grasp,'arc':arc,'new_physics_steps':0,'dynamic_admission':False,'scope':'Prior actual full-task acquisition-state geometric regression with revised left arm, not prediction of changed closed-loop approach state.'};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
