"""Saved-state first-impact kinematics and self-contact clearance counterfactuals."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
folder=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
records=[];state_samples=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 policy=f['policy/walker_onnx'];pr=policy['physics_row'][:];pn=next(iter(policy['input']))
 for k in [6400,6560,6720,6800,6840,6864,6872,6880,6881,6888,6904,6920,6960,7040]:
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  feet=[]
  for side in ['left','right']:
   bid=m.body(side+'_ankle_roll_link').id;gs=[g for g in range(m.ngeom) if m.geom_bodyid[g]==bid and m.geom_contype[g]]
   g=min(gs,key=lambda z:d.geom_xpos[z,2]-m.geom_size[z,0]);jac=np.zeros((3,m.nv));mujoco.mj_jac(m,d,jac,None,d.geom_xpos[g],bid)
   feet.append({'side':side,'geom':m.geom(g).name,'height_m':float(d.geom_xpos[g,2]-m.geom_size[g,0]),'velocity_mps':(jac@d.qvel).tolist(),'Jqacc_mps2':(jac@d.qacc).tolist()})
  pi=int(np.searchsorted(pr,k,side='right')-1);obs=policy['input'][pn][pi].reshape(-1)
  records.append({'row':k,'time':float(d.time),'base_v':d.qvel[:6].tolist(),'feet':feet,'policy_command':obs[-3:].tolist(),'raw_leg_targets':f['interpolation/requested'][k][:12].tolist(),'applied_leg_targets':f['interpolation/applied'][k][:12].tolist(),'base_xyz':d.qpos[:3].tolist(),'palm_xyz':d.site_xpos[m.site('right_palm').id].tolist()})
 # Sample every40ms plus every recorded forbidden contact's first state.
 keys=sorted(set([*range(6400,10000,16),8092,8581]))
 state_samples=[f['substep/integration_before'][k] for k in keys]
qa=m.jnt_qposadr[m.joint('left_elbow_joint').id]
hand=[g for g in range(m.ngeom) if m.geom_contype[g] and 'left_hand' in m.body(int(m.geom_bodyid[g])).name];thigh=m.geom('g2_col').id
clearance=[]
for offset in [0.,-.05,-.1,-.15,-.2]:
 minimum=.10;worst=None
 for k,state in zip(keys,state_samples):
  mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);d.qpos[qa]+=offset;mujoco.mj_kinematics(m,d)
  for g in hand:
   gap=float(mujoco.mj_geomDistance(m,d,thigh,g,.10,None))
   if gap<minimum:minimum=gap;worst={'row':k,'geom':m.geom(g).name}
 clearance.append({'left_elbow_offset_rad':offset,'min_clearance_m':minimum,'worst':worst})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'first_over10mm_step':6881,'first_over10mm_time':17.2025,'foot_records':records,'left_hand_thigh_static_offsets':clearance,'dynamic_admission':False,'production_accepted':False}
c.write(E/'C2_CONTACT_CAUSAL_KINEMATICS.json',report);finish(report)
