"""D3 saved-state left-arm clearance recovery; no dynamic or scope admission."""
import os
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from .planned_tripod_r2 import forbidden_robot_contacts
from .convex_projection_clearance import ProjectionClearance

def main():
 folder=E/'jobs/D_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);obj=m.body('red_block').id
 with h5py.File(folder/'TRACE.h5','r') as f:
  q=f['substep/qpos'][:];v=f['substep/qvel'][:];contacts=f['contacts/rows'][:];times=f['substep/time_before'][:];initial=f['initial_integration_state'][:]
  source_config=c.read(R/'branches/A/source/model_config.json');left_index=source_config['joint_names'].index('left_elbow_joint')
  requested=f['interpolation/requested'][:,left_index];default=source_config['default_joint_pos']['left_elbow_joint']
  transition_fraction=np.clip((requested-default)/-.10,0.,1.)
 names=['left_elbow_joint','left_shoulder_roll_joint'];jids=[m.joint(x).id for x in names];qa=m.jnt_qposadr[jids];va=m.jnt_dofadr[jids];aids=np.array([m.actuator(n).id for n in names])
 collision=c.read(folder.parent/'RECORDED_QUALITY.json')['forbidden_pairs'];pair=next(iter(collision)).split('|');gs=[m.geom(n).id for n in pair]
 hands=[g for g in range(m.ngeom) if m.geom_contype[g] and 'left_hand' in m.body(int(m.geom_bodyid[g])).name]
 projection=ProjectionClearance(m,[gs[0],*hands])
 rows=np.unique(np.r_[np.arange(0,len(q),160),np.arange(max(0,len(q)-800),len(q),8),len(q)-1]);variants=[]
 def evaluate(row,delta,check_torque=False):
  d.qpos[:]=q[row];d.qvel[:]=0.;d.qpos[qa]+=delta
  if np.any(d.qpos[qa]<m.jnt_range[jids,0]) or np.any(d.qpos[qa]>m.jnt_range[jids,1]):return False,-1.,-1.
  mujoco.mj_forward(m,d);gap=min(projection.gap(d,gs[0],g) for g in hands);bad=forbidden_robot_contacts(m,d,obj)
  torque=float(np.min(np.minimum(d.qfrc_bias[va]-m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1]-d.qfrc_bias[va])))
  return not bad and torque>=0.,gap,torque
 for elbow,roll in [(0.,0.),(-.05,0.),(-.1,0.),(-.15,0.),(-.2,0.),(0.,.05),(0.,.1),(0.,.15),(0.,.2),(-.05,.05),(-.1,.05)]:
  minimum=1.;valid=True;torque=1e9
  for row in rows:
   ok,gap,t=evaluate(int(row),np.array([elbow,roll]));valid &= ok;minimum=min(minimum,gap);torque=min(torque,t)
  variants.append({'joint_delta_rad':[elbow,roll],'all_sampled_states_forbidden_free':bool(valid),'minimum_pair_distance_m':minimum,'minimum_changed_arm_static_torque_margin_Nm':torque,'cost':elbow**2+roll**2,'valid':bool(valid and minimum>=.012)})
 qualified=sorted([r for r in variants if r['valid']],key=lambda x:x['cost']);selected=qualified[0] if qualified else None;full=None
 if selected:
  minimum=1.;active_minimum=1.;valid=True;minimum_row=None;torque=1e9;delta=np.array(selected['joint_delta_rad'])
  for row in range(len(q)):
   # Fade the additional target during the already planned2s compact-arm setup.
   fraction=float(transition_fraction[row])
   ok,gap,t=evaluate(row,delta*fraction);valid &= ok;torque=min(torque,t)
   if gap<minimum:minimum=gap;minimum_row=row
   if fraction>=1.-1e-6:active_minimum=min(active_minimum,gap)
  full={'rows':len(q),'forbidden_free':bool(valid),'minimum_pair_distance_m':minimum,'minimum_row':minimum_row,'minimum_static_torque_margin_Nm':torque,'target_transition_seconds':2.,'after_full_clearance_pose_minimum_pair_distance_m':active_minimum,'fraction_from_actual_saved_nominal_left_elbow_request':True}
 report={'physics_steps':0,'policy_calls':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'distance_method':'Positive finite-axis convex projection separation lower bound, all left-hand collision geometries against thigh; negative can be inconclusive. Does not rely on known zero-return mesh distance API.','failure_pair':pair,'failure_bodies':[m.body(int(m.geom_bodyid[g])).name for g in gs],'candidate_joints':names,'sampled_rows':len(rows),'candidates':variants,'selected':selected,'full_saved_trajectory_check':full,'passed':bool(full and full['forbidden_free'] and full['after_full_clearance_pose_minimum_pair_distance_m']>=.012),'dynamic_qualified':False,'closed_D_method_reopened':False,'production_accepted':False,'scope':'Read-only poststep counterfactual left-arm geometry and static motor feasibility across actual D3 trajectory. No locomotion or control rollout, no altered-trajectory guarantee.'}
 c.write(E/'D3_LEFT_ARM_CLEARANCE_RECOVERY_STATIC_R3.json',report);finish(report)

if __name__=='__main__':main()
