"""Static D approach arm plan: hand clears the table before a single walking leg."""
import numpy as np,h5py,mujoco
from scipy.optimize import minimize
from .work import E,c,finish
from .safe_approach_r3 import hand_bounds
folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(folder/'TRACE.h5','r') as f:mujoco.mj_setState(m,d,f['initial_integration_state'][:],mujoco.mjtState.mjSTATE_INTEGRATION)
names=['right_'+n+'_joint' for n in ['shoulder_pitch','shoulder_roll','shoulder_yaw','elbow','wrist_roll','wrist_pitch','wrist_yaw']];jids=[m.joint(n).id for n in names];qa=m.jnt_qposadr[jids];va=m.jnt_dofadr[jids];aids=[m.actuator(n).id for n in names];left=m.jnt_qposadr[m.joint('left_elbow_joint').id];initial=d.qpos.copy();seed=initial[qa].copy();sid=m.site('right_palm').id
mujoco.mj_forward(m,d);top=float(d.geom_xpos[m.geom('table_top').id,2]+m.geom_size[m.geom('table_top').id,2]);base=d.qpos[:3].copy();rot=d.xmat[m.body('pelvis').id].reshape(3,3);goal=base+rot@np.array([.10,-.22,.25]);feet=np.array([d.xpos[m.body(s+'_ankle_roll_link').id,:2] for s in ['left','right']]);center=feet.mean(0)
def fk(x):
 d.qpos[:]=initial;d.qpos[qa]=x;d.qpos[left]=initial[left]-.10;d.qvel[:]=0.;mujoco.mj_forward(m,d)
 return d.site_xpos[sid].copy()
def cost(x):
 palm=fk(x);com=d.subtree_com[m.body('base').id,:2]
 return 120.*np.sum((palm-goal)**2)+.15*np.sum((x-seed)**2)+120.*np.sum((com-center)**2)
def constraints(x):
 fk(x);low,_=hand_bounds(m,d);com=d.subtree_com[m.body('base').id,:2]
 ground_margin=1.;forbidden_margin=1.
 for ct in d.contact:
  bs=[m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1,ct.geom2]];gn=[m.geom(g).name for g in [ct.geom1,ct.geom2]]
  if 'ground' in gn and any('ankle_roll' in b for b in bs):ground_margin=min(ground_margin,float(ct.dist)+.01)
  elif any('hand' in b or b.endswith('_link') for b in bs):forbidden_margin=min(forbidden_margin,float(ct.dist))
 torque=np.minimum(d.qfrc_bias[va]-m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1]-d.qfrc_bias[va])
 return np.r_[low[2]-top-.09,com-(feet.min(0)-[.09,.015]),feet.max(0)+[.09,.015]-com,torque,ground_margin,forbidden_margin]
result=minimize(cost,seed,method='SLSQP',bounds=list(map(tuple,m.jnt_range[jids])),constraints=[{'type':'ineq','fun':constraints}],options={'maxiter':100,'ftol':1e-8})
end=fk(result.x);cons=constraints(result.x);path=[]
for a in np.linspace(0,1,61):
 # Left and right arm changes are commanded continuously on the runtime plant.
 x=seed+a*(result.x-seed);fk(x);d.qpos[left]=initial[left]-.10*a;mujoco.mj_forward(m,d)
 forbidden=[]
 for ct in d.contact:
  bs=[m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1,ct.geom2]];gn=[m.geom(g).name for g in [ct.geom1,ct.geom2]]
  if 'ground' in gn and any('ankle_roll' in b for b in bs):continue
  if any('hand' in b or b.endswith('_link') for b in bs) and ct.dist<0:forbidden.append({'geoms':gn,'penetration_m':float(-ct.dist)})
 path.append({'fraction':float(a),'forbidden':forbidden})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'joint_names':names,'arm_target_rad':result.x.tolist(),'left_elbow_offset_rad':-.10,'initial_arm_rad':seed.tolist(),'palm_goal_xyz':goal.tolist(),'palm_planned_xyz':end.tolist(),'minimum_table_clearance_m':float(cons[0]+.09),'min_constraint':float(min(cons)),'iterations':int(result.nit),'message':str(result.message),'static_endpoint_valid':bool(result.success and min(cons)>=-1e-6),'initial_pose_path_samples':path,'initial_pose_path_forbidden_free':not any(x['forbidden'] for x in path),'purpose':'D compact hand-clear approach configuration before one continuous forward walking leg; avoid post-staging stop/raise/restart. Exact same physical plant, no dynamic result.','dynamic_admission':False,'production_accepted':False}
c.write(E/'D_COMPACT_APPROACH_POSE.json',report);finish(report)
