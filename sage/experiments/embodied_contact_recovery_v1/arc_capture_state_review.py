"""Compare measured failed capture endpoints to scratch kinematic targets."""
import sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,c,finish
from .planned_tripod_world_offset import FINGER_NAMES,contact_geometry,forbidden_robot_contacts
from .tripod_recontact import plan_recontact

def main(config):
 cfg=c.read(config);rows=[]
 for key in cfg['jobs']:
  job=E/'jobs'/key;folder=job/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
  planned=c.read(job/'MEASURED_TRIPOD_PLAN.json');arm_names=['right_shoulder_pitch_joint','right_shoulder_roll_joint','right_shoulder_yaw_joint','right_elbow_joint','right_wrist_roll_joint','right_wrist_pitch_joint','right_wrist_yaw_joint']
  arm=np.array([m.jnt_qposadr[m.joint(x).id] for x in arm_names]);fingers=np.array([m.jnt_qposadr[m.joint('right_hand_'+x+'_joint').id] for x in FINGER_NAMES])
  with h5py.File(folder/'TRACE.h5','r') as f:
   q=f['substep/qpos'][-1];v=f['substep/qvel'][-1];d.qpos[:]=q;d.qvel[:]=v;mujoco.mj_forward(m,d)
   item={'job':key,'row':len(f['substep/qpos'])-1,'actual_grasp':contact_geometry(m,d,m.body('red_block').id),'retarget':plan_recontact(m,d,m.body('red_block').id),'arm_error_rad':(np.asarray(planned['arm_target_rad'])-q[arm]).tolist(),'finger_error_rad':(np.asarray(planned['finger_target_rad'])-q[fingers]).tolist(),'actual_arm_rad':q[arm].tolist(),'actual_finger_rad':q[fingers].tolist(),'base_displacement':(q[:3]-f['substep/qpos'][0,:3]).tolist(),'finger_last_telemetry':f['finger_governor/control'][-1].tolist()}
  for label,aa,ff in [('commanded_fingers_only',False,True),('commanded_arm_only',True,False),('all_commanded',True,True)]:
   d.qpos[:]=q;d.qvel[:]=0
   if aa:d.qpos[arm]=planned['arm_target_rad']
   if ff:d.qpos[fingers]=planned['finger_target_rad']
   mujoco.mj_forward(m,d);item[label]={'grasp':contact_geometry(m,d,m.body('red_block').id),'forbidden':forbidden_robot_contacts(m,d,m.body('red_block').id)}
  rows.append(item)
 report={'complete':True,'new_physics_steps':0,'rows':rows,'production_accepted':False};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
