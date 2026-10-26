"""Measured finger convergence and contact cause for the second C attempt."""
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
folder=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
aids=[i for i in range(m.nu) if m.actuator(i).name.startswith('right_hand')];jids=m.actuator_trnid[aids,0];qa=m.jnt_qposadr[jids];va=m.jnt_dofadr[jids];obj=m.body('red_block').id
with h5py.File(folder/'TRACE.h5','r') as f:
 rows=f['contacts/rows'][:];hand_rows=[r for r in rows if any(m.geom_bodyid[int(g)]==obj for g in r[1:3]) and any('right_hand' in m.body(int(m.geom_bodyid[int(g)])).name for g in r[1:3])]
 samples=[]
 for sec in [30.,32.,34.,35.,36.,37.,38.,39.,40.,42.]:
  k=int(round(sec/.0025));mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  names=[m.actuator(a).name for a in aids];error=d.ctrl[aids]-d.qpos[qa]
  samples.append({'time':sec,'finger_q_rad':d.qpos[qa].tolist(),'finger_v_rps':d.qvel[va].tolist(),'actual_position_commands_rad':d.ctrl[aids].tolist(),'preload_rad':error.tolist(),'actuator_torque_Nm':f['substep/actuator_force'][k][aids].tolist(),'bias_torque_Nm':d.qfrc_bias[va].tolist(),'passive_torque_Nm':d.qfrc_passive[va].tolist(),'palm_xyz':d.site_xpos[m.site('right_palm').id].tolist(),'object_xyz':d.xpos[obj].tolist()})
 # Free-motion velocity estimate from current physical PD and viscous damping, explicitly excluding contact/coupling.
 envelope=[]
 for a,j in zip(aids,jids):
  kp=float(m.actuator_gainprm[a,0]);visc=float(-m.actuator_biasprm[a,2]+m.dof_damping[m.jnt_dofadr[j]])
  envelope.append({'joint':m.joint(j).name,'kp':kp,'actuator_plus_joint_viscous':visc,'armature':float(m.dof_armature[m.jnt_dofadr[j]]),'approx_velocity_under_cap003_rps':kp*.03/visc,'approx_velocity_under_cap002_rps':kp*.02/visc})
report={'physics_steps':0,'source':str(folder),'source_sha256':c.sha(folder/'TRACE.h5'),'finger_names':names,'samples':samples,'object_hand_contact_rows':len(hand_rows),'first_object_hand_contact_s':float(f['substep/time_before'][int(hand_rows[0][0])]) if hand_rows else None,'free_motion_estimates':envelope,'estimate_limitations':'Linear viscous estimate only; actual measured traces above include bias, coupling and contact. Not a force threshold or physical admission.','source_close_duration_status':'Pipeline reports target fraction1.0 and later HOLD_CAP0.02; actual joint convergence/contact must be assessed separately.','production_accepted':False}
c.write(E/'C2_CAPTURE_RESPONSE_ANALYSIS.json',report);finish(report)
