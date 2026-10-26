"""Measured pre-loss rigid-body motion and ideal friction wrench feasibility."""
import sys
from pathlib import Path
import numpy as np,h5py,mujoco
from scipy.spatial.transform import Rotation
from .work import E,c,finish
from .grasp_force_certificate import certify
from .planned_tripod_r2 import contact_geometry

def main(config):
 cfg=c.read(config);records=[]
 for key in cfg['jobs']:
  folder=E/'jobs'/key/'episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);obj=m.body('red_block').id;site=m.site('right_palm').id;values=[];r0=None;obj0=None
  with h5py.File(folder/'TRACE.h5','r') as f:
   n=len(f['substep/qpos']);indices=sorted(set([0,*range(400,n,400),*range(max(0,n-160),n,16),n-1]))
   for i in indices:
    mujoco.mj_setState(m,d,f['substep/integration_before'][i],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d);w=d.site_xmat[site].reshape(3,3);o=d.xmat[obj].reshape(3,3)
    if r0 is None:r0=w.copy();obj0=w.T@o
    vel=np.zeros(6);mujoco.mj_objectVelocity(m,d,mujoco.mjtObj.mjOBJ_SITE,site,vel,0)
    values.append({'row':i,'time':float(d.time),'base_velocity':d.qvel[:6].tolist(),'base_tilt_deg':float(np.degrees(np.arccos(np.clip(d.xmat[m.body('base').id].reshape(3,3)[2,2],-1,1)))),'palm_rotation_change_deg':float(np.degrees(np.linalg.norm(Rotation.from_matrix(w@r0.T).as_rotvec()))),'object_relative_rotation_change_deg':float(np.degrees(np.linalg.norm(Rotation.from_matrix(w.T@o@obj0.T).as_rotvec()))),'object_tilt_deg':float(np.degrees(np.arccos(np.clip(o[2,2],-1,1)))),'palm_velocity_world_angular_linear':vel.tolist(),'contact':contact_geometry(m,d,obj),'ideal_certificate':certify(m,d,obj)})
  records.append({'job':key,'samples':values})
 report={'complete':True,'new_physics_steps':0,'records':records,'empirical_calibration':False,'production_accepted':False};c.write(E/cfg['output'],report);finish(report)
if __name__=='__main__':main(sys.argv[1])
