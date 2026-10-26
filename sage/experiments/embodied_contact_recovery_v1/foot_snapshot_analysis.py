"""Read contact kinematics and actuator sensitivity from saved states, no integration."""
import os
from pathlib import Path
import h5py
import numpy as np
import mujoco
from .work import R,E,finish,c

source=R/'jobs/A_target_02/episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
leg_names=[s+'_'+j+'_joint' for s in ['left','right'] for j in ['hip_pitch','hip_roll','hip_yaw','knee','ankle_pitch','ankle_roll']]
aids=np.array([m.actuator(n).id for n in leg_names])
body_ids=[m.body(s+'_ankle_roll_link').id for s in ['left','right']]
feet=[[g for g in range(m.ngeom) if m.geom_bodyid[g]==b and m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE and m.geom_contype[g]] for b in body_ids]
records=[]
with h5py.File(source/'TRACE.h5','r') as f:
 for k in [5400,5440,5480,5500,5510,5520,5529,5540,5560,5600,5680,5760,5880,6000]:
  d.qpos[:]=f['substep/qpos'][k-1];d.qvel[:]=f['substep/qvel'][k-1];d.qacc_warmstart[:]=f['substep/qacc'][k-1];d.ctrl[:]=f['substep/ctrl'][k]
  mujoco.mj_forward(m,d)
  warm=d.qacc_warmstart.copy();acc=d.qacc.copy();control=d.ctrl.copy()
  points=[]
  for bid,gs in zip(body_ids,feet):
   g=min(gs,key=lambda i:d.geom_xpos[i,2]-m.geom_size[i,0]);jp=np.zeros((3,m.nv));jr=np.zeros_like(jp)
   mujoco.mj_jac(m,d,jp,jr,d.geom_xpos[g],bid)
   points.append({'side':m.body(bid).name,'geom':m.geom(g).name,'height':float(d.geom_xpos[g,2]-m.geom_size[g,0]),'velocity':(jp@d.qvel).tolist(),'acceleration':(jp@d.qacc).tolist(),'J':jp})
  response=np.zeros((m.nv,len(aids)))
  for j,a in enumerate(aids):
   d.ctrl[:]=control;d.ctrl[a]+=.1;d.qacc_warmstart[:]=warm;mujoco.mj_forward(m,d);response[:,j]=(d.qacc-acc)/.1
  for p in points:p['z_acceleration_per_Nm']=(p.pop('J')[2]@response).tolist()
  records.append({'row':k,'time':k*.0025,'base_velocity':d.qvel[:6].tolist(),'base_acceleration':acc[:6].tolist(),'leg_control':control[aids].tolist(),'feet':points,'base_response':response[:6].tolist()})
report={'physics_steps':0,'source_sha256':c.sha(source/'TRACE.h5'),'records':records,'leg_actuators':leg_names,'method':'mj_forward finite actuator sensitivity, no mj_step or policy calls','production_accepted':False}
c.write(E/'FOOT_IMPACT_SAVED_STATE_ANALYSIS.json',report);finish(report)
