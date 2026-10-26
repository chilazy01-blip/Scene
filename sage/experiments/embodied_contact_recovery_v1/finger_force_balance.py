"""Recompute saved force and acceleration with the initial plant; no integration."""
import numpy as np, h5py, mujoco
from .work import E,c,finish

folder=E/'jobs/C_development_02/episode'
m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
aids=np.array([a for a in range(m.nu) if m.actuator(a).name.startswith('right_hand')])
jids=m.actuator_trnid[aids,0];va=m.jnt_dofadr[jids]
samples=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 for sec in [34.,38.,39.,39.5,40.,42.]:
  k=round(sec/.0025)
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION)
  mujoco.mj_forward(m,d)
  samples.append({'time':sec,'qacc_recorded':f['substep/qacc'][k][va].tolist(),
   'qacc_recomputed':d.qacc[va].tolist(),
   'qacc_max_error_all':float(np.max(np.abs(d.qacc-f['substep/qacc'][k]))),
   'actuator_error_all':float(np.max(np.abs(d.actuator_force-f['substep/actuator_force'][k]))),
   'constraint_error_all':float(np.max(np.abs(d.qfrc_constraint-f['substep/qfrc_constraint'][k]))),
   'qfrc_constraint':d.qfrc_constraint[va].tolist(),
   'qfrc_actuator':d.qfrc_actuator[va].tolist(),'qfrc_bias':d.qfrc_bias[va].tolist(),
   'qfrc_passive':d.qfrc_passive[va].tolist(),'qvel':d.qvel[va].tolist(),
   'friction_constraints':[{'dof':int(d.efc_id[i]),'force':float(d.efc_force[i]),'velocity':float(d.efc_vel[i]),'frictionloss':float(d.efc_frictionloss[i])} for i in range(d.nefc) if int(d.efc_type[i])==int(mujoco.mjtConstraint.mjCNSTR_FRICTION_DOF) and d.efc_id[i] in va]})
report={'physics_steps':0,'source':str(folder),'finger_names':[m.joint(j).name for j in jids],
 'joint_frictionloss_Nm':m.dof_frictionloss[va].tolist(),'solref_friction':m.dof_solref[va].tolist(),
 'solimp_friction':m.dof_solimp[va].tolist(),'joint_damping':m.dof_damping[va].tolist(),
 'actuator_gain':m.actuator_gainprm[aids].tolist(),'actuator_bias':m.actuator_biasprm[aids].tolist(),
 'samples':samples,'initial_plant_reproduces_sampled_dynamics':all(s['qacc_max_error_all']<1e-9 and s['actuator_error_all']<1e-9 and s['constraint_error_all']<1e-9 for s in samples),
 'causal_boundary':'Static source search found no damping/gain mutations in run.py or ik/*.py; sampled complete dynamics additionally tested. This is not an all-step plant-identity proof.',
 'production_accepted':False}
c.write(E/'C2_FINGER_FORCE_BALANCE.json',report);finish(report)
