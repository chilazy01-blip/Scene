"""Static self-contact cause and minimum posture correction on saved states."""
import numpy as np
import h5py
import mujoco
from scipy.optimize import minimize
from .work import E,finish,c
source=E/'jobs/C_development_01r/episode';m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
pairs=[('g2_col','left_hand_thumb_2_link_col'),('g11_col','right_hand_thumb_2_link_col'),('g2_col','gripper0_left_g0_col'),('g2_col','gripper0_left_g1_col')]
gids=[(m.geom(a).id,m.geom(b).id) for a,b in pairs]
joints=['left_shoulder_roll_joint','left_elbow_joint','right_shoulder_roll_joint','right_elbow_joint'];qa=np.array([m.jnt_qposadr[m.joint(n).id] for n in joints])
records=[]
with h5py.File(source/'TRACE.h5','r') as f:
 for k in [0,74,151,333,1599,20000,60000]:
  original=f['substep/qpos'][k];d.qpos[:]=original;d.qvel[:]=0
  def distances(x):
   d.qpos[:]=original;d.qpos[qa]=x;mujoco.mj_kinematics(m,d);mujoco.mj_comPos(m,d)
   return np.array([mujoco.mj_geomDistance(m,d,a,b,.05,None) for a,b in gids])
  seed=original[qa].copy();baseline=distances(seed)
  result=minimize(lambda x:np.sum((x-seed)**2),seed,method='SLSQP',
                  bounds=[(max(m.jnt_range[m.joint(n).id,0],x-.3),min(m.jnt_range[m.joint(n).id,1],x+.3)) for n,x in zip(joints,seed)],
                  constraints=[{'type':'ineq','fun':lambda x:distances(x)-.004}],options={'maxiter':80,'ftol':1e-10})
  final=distances(result.x);assert np.array_equal(d.qpos[np.setdiff1d(np.arange(m.nq),qa)],original[np.setdiff1d(np.arange(m.nq),qa)])
  mujoco.mj_forward(m,d)
  records.append({'row':k,'time':float(f['substep/time_before'][k]),'baseline_q':seed.tolist(),'baseline_distances_m':baseline.tolist(),
                  'optimized_q':result.x.tolist(),'delta_q':(result.x-seed).tolist(),'clearances_m':final.tolist(),
                  'feasible':bool(result.success and min(final)>=.004-1e-5),'static_bias_torque_Nm':[float(d.qfrc_bias[m.jnt_dofadr[m.joint(n).id]]) for n in joints]})
report={'physics_steps':0,'policy_forwards':0,'method':'Saved geometry4mm clearance constrained nearest posture; no plant edits or execution',
        'pairs':pairs,'joints':joints,'records':records,'production_accepted':False,'remaining':'Check commanded equilibrium under measured gravity and online gait before execution admission'}
c.write(E/'REST_POSTURE_SELF_CONTACT_ANALYSIS.json',report);finish(report)
