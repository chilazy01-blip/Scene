"""Prepare an explicit named-joint initial condition without integrating dynamics."""
import os
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
job=Path(os.environ['CONTINUOUS_JOB_DIR']);source=E/'jobs/C_development_01r/episode'
m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(source/'TRACE.h5','r') as f:before=f['initial_integration_state'][:]
mujoco.mj_setState(m,d,before,mujoco.mjtState.mjSTATE_INTEGRATION)
config=c.read(R/'branches/A/source/model_config.json');contract=c.read(R.parent/'generated/GLOCAL_NEW/package_r2/CONTRACT.json')
changes=[]
for n in contract['joint_names']:
 j=m.joint(n).id;a=m.jnt_qposadr[j];value=float(np.clip(config['default_joint_pos'].get(n,0.),*m.jnt_range[j]))
 if value!=d.qpos[a]:changes.append({'joint':n,'before_rad':float(d.qpos[a]),'after_rad':value})
 d.qpos[a]=value
mujoco.mj_forward(m,d);after=np.empty_like(before);mujoco.mj_getState(m,d,after,mujoco.mjtState.mjSTATE_INTEGRATION)
np.savez_compressed(job/'NAMED_INITIAL_STATE.npz',integration_state=after,original_integration_state=before)
contacts=[{'geoms':[m.geom(x.geom1).name,m.geom(x.geom2).name],'distance_m':float(x.dist)} for x in d.contact]
clearances={}
for side,thigh in [('left','g2_col'),('right','g11_col')]:
 clearances[side]={n:float(mujoco.mj_geomDistance(m,d,m.geom(thigh).id,m.geom(n).id,.1,None)) for n in [side+'_hand_thumb_2_link_col','gripper0_'+side+'_g0_col','gripper0_'+side+'_g1_col'] if mujoco.mj_name2id(m,mujoco.mjtObj.mjOBJ_GEOM,n)>=0}
report={'physics_steps':0,'initial_condition_changes_only_before_first_integration':changes,'source':str(source),'original_state_sha256':c.sha(source/'TRACE.h5'),'prepared_state':str(job/'NAMED_INITIAL_STATE.npz'),'contacts':contacts,'hand_thigh_clearances_m':clearances,'plant_and_actuators_unchanged':True,'dynamic_admission':False}
c.write(E/'NAMED_INITIAL_POSTURE_PREFLIGHT.json',report);finish(report)
