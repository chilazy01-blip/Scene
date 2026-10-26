"""Locate loss of measured grasp during C alignment using saved states/forces."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
obj=m.body('red_block').id;oa=m.jnt_qposadr[m.joint('red_block_joint').id];od=m.jnt_dofadr[m.joint('red_block_joint').id];sid=m.site('right_palm').id
with h5py.File(folder/'TRACE.h5','r') as f:
 t=f['substep/time_before'][:];contacts=f['contacts/rows'][:];world=f['contacts/world_force'][:];start=int(f['feedback/physics_row'][0]);end=min(len(t),start+4800)
 hand=np.zeros(len(t),int);objforce=np.zeros((len(t),3));handforce=np.zeros((len(t),3));support=np.zeros(len(t));dist=np.zeros(len(t))
 for row,w in zip(contacts,world):
  k,g1,g2=map(int,row[:3]);b1,b2=map(int,m.geom_bodyid[[g1,g2]])
  if obj not in [b1,b2]:continue
  force=w*(1 if b2==obj else -1);other=g1 if b2==obj else g2;objforce[k]+=force
  if 'right_hand' in m.body(int(m.geom_bodyid[other])).name:hand[k]+=1;handforce[k]+=force;dist[k]=max(dist[k],float(-row[3]))
  if m.geom(other).name=='table_white_top':support[k]+=force[2]
 nohand=np.flatnonzero(hand[start:end]==0);loss=start+int(nohand[0]) if len(nohand) else None
 records=[]
 indices=sorted(set([max(0,start-80),start,*range(start,end,80),*([max(start,loss-1),loss,min(end-1,loss+1)] if loss is not None else [])]))
 maxbalance=0.
 for k in indices:
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  rot=d.xmat[obj].reshape(3,3);palm=d.site_xpos[sid].copy();pr=d.site_xmat[sid].reshape(3,3)
  residual=objforce[k]+m.body_mass[obj]*m.opt.gravity-m.body_mass[obj]*f['substep/qacc'][k][od:od+3];maxbalance=max(maxbalance,float(np.max(abs(residual))))
  records.append({'row':k,'time':float(t[k]),'object_xyz':d.xpos[obj].tolist(),'palm_xyz':palm.tolist(),'object_in_palm':(pr.T@(d.xpos[obj]-palm)).tolist(),'object_tilt_deg':float(np.degrees(np.arccos(np.clip(rot[2,2],-1,1)))),'object_linear_velocity_mps':d.qvel[od:od+3].tolist(),'hand_contacts':int(hand[k]),'hand_force_world_N':handforce[k].tolist(),'target_support_N':float(support[k]),'hand_object_penetration_m':float(dist[k]),'linear_force_balance_residual_N':residual.tolist()})
 firstbad=contacts[contacts[:,3]<-.01][0];feedback={'physics_row':f['feedback/physics_row'][:].tolist(),'state':f['feedback/state'][:].tolist(),'observation':f['feedback/observation'][:].tolist()}
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'C_alignment_start_row':start,'C_alignment_start_time':float(t[start]),'first_zero_hand_contacts_during_alignment_row':loss,'first_zero_hand_contacts_time':float(t[loss]) if loss is not None else None,'records':records,'force_balance_max_abs_N':maxbalance,'first_over10mm':{'row':int(firstbad[0]),'time':float(t[int(firstbad[0])]),'geoms':[m.geom(int(g)).name for g in firstbad[1:3]],'penetration_m':float(-firstbad[3])},'feedback':feedback,'method_C_remains_closed':True,'production_accepted':False}
c.write(E/'C3_PLACEMENT_LOSS_CAUSAL_ANALYSIS.json',report);finish(report)
