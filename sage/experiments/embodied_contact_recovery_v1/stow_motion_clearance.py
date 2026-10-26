"""Find minimal outward stow offset against every saved initial-gait posture."""
import numpy as np,h5py,mujoco
from scipy.optimize import brentq
from .work import E,c,finish
folder=E/'jobs/walk_stop_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
qa=m.jnt_qposadr[m.joint('right_shoulder_roll_joint').id];thigh=m.geom('g11_col').id
hands=[g for g in range(m.ngeom) if m.geom_contype[g] and ('right_hand' in m.body(int(m.geom_bodyid[g])).name or (m.geom(g).name or '').startswith('gripper0_right'))]
with h5py.File(folder/'TRACE.h5','r') as f:
 q=f['substep/qpos'][:];q=np.concatenate([f['initial_integration_state'][1:1+m.nq][None],q[:-1]])
def evaluate(offset,details=False):
 minimum=1.;worst=None
 for k,state in enumerate(q):
  d.qpos[:]=state;d.qpos[qa]+=offset;mujoco.mj_kinematics(m,d)
  for g in hands:
   gap=float(mujoco.mj_geomDistance(m,d,thigh,g,.05,None))
   if gap<minimum:minimum=gap;worst={'row':k,'hand_geom':m.geom(g).name,'distance_m':gap}
 return (minimum,worst) if details else minimum
original=evaluate(0,True);outer=evaluate(-.15,True)
assert outer[0]>.015
root=brentq(lambda off:evaluate(off)-.015,-.15,0,xtol=1e-5)
chosen=-np.ceil(abs(root)/.01)*.01;gap,worst=evaluate(chosen,True)
report={'physics_steps':0,'source':str(folder),'source_sha256':c.sha(folder/'TRACE.h5'),'joint':'right_shoulder_roll_joint','original':original,'candidate_offset_rad':float(chosen),'measured_counterfactual_min_clearance_m':gap,'worst':worst,'scope':'Geometric counterfactual at every saved moving posture; dynamic validity still requires bounded window, current gains/plant unchanged','dynamic_admission':False}
c.write(E/'STOW_MOTION_CLEARANCE_ANALYSIS.json',report);finish(report)
