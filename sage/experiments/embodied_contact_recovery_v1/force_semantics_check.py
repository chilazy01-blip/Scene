"""Independently check pre-integration actuator forces and object contact-force sign."""
import numpy as np
import h5py,mujoco
from .work import E,finish,c
source=E/'jobs/C_development_01r/episode';m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
assert int(m.opt.integrator)==0 and np.all(m.actuator_dyntype==0)
with h5py.File(source/'TRACE.h5','r') as f:
 q=f['substep/qpos'][:];v=f['substep/qvel'][:];ctrl=f['substep/ctrl'][:];force=f['substep/actuator_force'][:];acc=f['substep/qacc'][:]
 mujoco.mj_setState(m,d,f['initial_integration_state'][:],mujoco.mjtState.mjSTATE_INTEGRATION)
 qb=np.vstack([d.qpos[None],q[:-1]]);vb=np.vstack([d.qvel[None],v[:-1]])
 expected=np.zeros_like(force)
 for a in range(m.nu):
  jid=int(m.actuator_trnid[a,0]);qa=m.jnt_qposadr[jid];va=m.jnt_dofadr[jid]
  assert m.actuator_gaintype[a]==0 and m.actuator_biastype[a] in [0,1]
  expected[:,a]=m.actuator_gainprm[a,0]*ctrl[:,a]
  if m.actuator_biastype[a]==1:expected[:,a]+=m.actuator_biasprm[a,0]+m.actuator_biasprm[a,1]*qb[:,qa]+m.actuator_biasprm[a,2]*vb[:,va]
  if m.actuator_forcelimited[a]:expected[:,a]=np.clip(expected[:,a],*m.actuator_forcerange[a])
 error=np.max(abs(expected-force),axis=0)
 obj=m.body('red_block').id;od=m.jnt_dofadr[m.joint('red_block_joint').id];mass=m.body_mass[obj]
 rows=f['contacts/rows'][:];world=f['contacts/world_force'][:];total=np.zeros((len(q),3));events=0
 for row,w in zip(rows,world):
  k,g,h=map(int,row[:3]);a=m.geom_bodyid[g]==obj;b=m.geom_bodyid[h]==obj
  if a!=b:total[k]+=w*(1 if b else -1);events+=1
 predicted=total/mass+m.opt.gravity[None];residual=np.linalg.norm(predicted-acc[:,od:od+3],axis=1)
 # Zero velocity after settling removes tiny air-drag terms. Contact force points
 # and qacc belong to the pre-integration dynamics at time_before.
 settled=np.linalg.norm(vb[:,od:od+3],axis=1)<1e-5
 assert float(max(error))<1e-10
 assert np.any(settled) and float(max(residual[settled]))<1e-3
 report={'passed':True,'physics_steps':0,'policy_calls':0,'actuator_force_max_error_Nm':float(max(error)),
         'per_actuator_force_errors':dict(zip([m.actuator(a).name for a in range(m.nu)],map(float,error))),
         'object_contact_records':events,'object_force_sign':'Logged world force acts on geom2; negate for object on geom1',
         'object_force_balance_settled_max_acceleration_error_mps2':float(max(residual[settled])),
         'object_force_balance_all_max_acceleration_error_mps2':float(max(residual)),
         'time_alignment':'Euler contact force, contact location, qacc and actuator_force correspond to time_before and integration_before; qpos/qvel fields are after the step.',
         'production_calibration':False,'production_accepted':False}
c.write(E/'FORCE_AND_TIME_SEMANTICS_CHECK.json',report);finish(report)
