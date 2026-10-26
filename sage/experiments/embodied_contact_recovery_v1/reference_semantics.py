"""Disambiguate motion reference, internal translated setpoint, and motor torque."""
import numpy as np,h5py,mujoco
from .work import E,P,c,finish
folder=E/'jobs/grasp_early_brake_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));contract=c.read(P/'generated/GLOCAL_NEW/package_r2/CONTRACT.json')
names=contract['joint_names'];qa=[m.jnt_qposadr[m.joint(n).id] for n in names];va=[m.jnt_dofadr[m.joint(n).id] for n in names];aids=[m.actuator(n).id for n in names]
with h5py.File(folder/'TRACE.h5','r') as f:
 issued=f['substep/issued_position_target'][-200:];nominal=f['substep/nominal_position_target'][-200:];q=f['substep/qpos'][-201:-1,qa];v=f['substep/qvel'][-201:-1,va];control=f['substep/ctrl'][-200:,aids]
 rows=[]
 for part,ids in [('legs',contract['inspection']['groups']['lower_body'][:12]),('torso',contract['inspection']['groups']['lower_body'][12:]),('left',contract['inspection']['groups']['left_arm']),('right',contract['inspection']['groups']['right_arm'])]:
  gains=contract['inspection']['controllers'][part]['attributes'];kp=np.asarray(gains['kp']);kd=np.asarray(gains['kd']);delta=issued[:,ids]-q[:,ids];nom=nominal[:,ids]-q[:,ids]
  for j,i in enumerate(ids):
   k=int(np.argmax(abs(delta[:,j])));rows.append({'group':part,'joint':names[i],'internal_translated_setpoint_error_rad':float(max(abs(delta[:,j]))),'intended_motion_reference_error_rad':float(max(abs(nom[:,j]))),'actual_control_range':control[:,i].min().item() if len(control)==0 else [float(control[:,i].min()),float(control[:,i].max())],'position_actuator_gain':float(m.actuator_gainprm[aids[i],0]),'actuator_bias':m.actuator_biasprm[aids[i]].tolist(),'retained_controller_kp':float(kp[j]),'retained_controller_kd':float(kd[j]),'internal_PD_at_peak':float(kp[j]*delta[k,j]-kd[j]*v[k,i])})
report={'physics_steps':0,'source':str(folder),'source_sha256':c.sha(folder/'TRACE.h5'),'rows':rows,'units':'Body29 actual controls are Nm motors;14 hand actual controls are position radians. nominal_position_target is source intended motion; issued_position_target is the adapter internal inverse-controller setpoint. Both errors retained; this analysis does not change thresholds or admission.'}
c.write(E/'REFERENCE_CONTROL_SEMANTICS.json',report);finish(report)
