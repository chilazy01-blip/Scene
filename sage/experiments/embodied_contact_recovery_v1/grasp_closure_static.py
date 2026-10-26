"""Kinematic acquisition sweep at the saved preclose pose; not a rollout."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
folder=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(folder/'TRACE.h5','r') as f:
 state=f['substep/integration_before'][15200];mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION)
q0=d.qpos.copy();obj=m.body('red_block').id
names=['thumb_0','thumb_1','thumb_2','index_0','index_1','middle_0','middle_1'];closed=np.array([.8,-.9,-1.5,1.4,1.5,1.4,1.5]);aids=[m.actuator('right_hand_'+n+'_joint').id for n in names];qa=m.jnt_qposadr[m.actuator_trnid[aids,0]]
rows=[]
for alpha in np.linspace(.25,1.,76):
 d.qpos[:]=q0;d.qpos[qa]=closed*alpha;mujoco.mj_forward(m,d)
 contact=[];forbidden=[]
 for x in d.contact:
  b=[int(m.geom_bodyid[g]) for g in [x.geom1,x.geom2]];bn=[m.body(z).name for z in b]
  if any(n.startswith('right_hand') for n in bn):
   item={'bodies':bn,'geoms':[m.geom(g).name for g in [x.geom1,x.geom2]],'distance_m':float(x.dist)}
   (contact if obj in b else forbidden).append(item)
 rows.append({'alpha':float(alpha),'object_contacts':contact,'forbidden_hand_contacts':forbidden})
report={'physics_steps':0,'policy_calls':0,'saved_row':15200,'saved_time':38.,'source':str(folder),
 'first_object_contact_alpha':next((r['alpha'] for r in rows if r['object_contacts']),None),
 'first_forbidden_hand_contact_alpha':next((r['alpha'] for r in rows if r['forbidden_hand_contacts']),None),
 'sweep':rows,'limitations':'Rigid kinematic closure holds object fixed; penetration after contact is not predicted physical motion. Only precontact path and first contact are useful for acquisition design.',
 'production_accepted':False}
c.write(E/'C2_GRASP_CLOSURE_STATIC.json',report);finish(report)
