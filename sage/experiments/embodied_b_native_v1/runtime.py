"""Named G1 adapter around unchanged official observation/history/action methods."""
from pathlib import Path
import sys,site,json,hashlib,collections,os
R=Path(os.environ['B_NATIVE_RUN_ROOT']).resolve();OLD=R.parent/'embodied_control_repair_20260925_v1'
assert R.name=='embodied_b_native_20260926_v1'
S0=Path('/data/wsj/main/scene_handoffs/embodied_dual_end_effector_audit_20260925_v1')
import sympy
assert sympy.__version__=='1.13.1' and 'numpy' not in sys.modules
sys.path.insert(0,str(OLD/'vendor'));site.addsitedir(str(OLD/'vendor'));sys.path.insert(0,str(OLD/'upstream'))
import numpy as np
import torch,onnxruntime as ort,pinocchio as pin,mujoco,yaml
torch.set_num_threads(1);torch.set_num_interop_threads(1)
assert np.__version__=='1.26.4' and ort.__version__=='1.22.1' and pin.__version__=='2.7.0'
from decoupled_wbc.control.robot_model.instantiation.g1 import instantiate_g1_robot_model
from decoupled_wbc.control.policy.g1_gear_wbc_policy import G1GearWbcPolicy
P=json.loads((R/'protocol/B_DYNAMIC.json').read_text())
SPEC=mujoco.mjtState.mjSTATE_INTEGRATION
CFG_PATH=OLD/'upstream/decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.yaml'
CFG=yaml.safe_load(CFG_PATH.read_text())
MAIN=yaml.safe_load((S0/'sources/groot/files/decoupled_wbc/control/main/teleop/configs/g1_29dof_gear_wbc.yaml').read_text())

def save(path,value):
 (R/path).write_text(json.dumps(value,indent=2)+'\n')

def make_model():
 m=mujoco.MjModel.from_xml_path(P['model']);assert m.opt.timestep==P['xml_dt']
 m.opt.timestep=P['dt'];d=mujoco.MjData(m)
 assert (m.nq,m.nv,m.nu,m.nmocap,m.neq)==(50,49,43,0,0)
 assert m.jnt_type[0]==mujoco.mjtJoint.mjJNT_FREE
 assert not np.any(m.body_gravcomp) and not np.any(d.qfrc_applied) and not np.any(d.xfrc_applied)
 return m,d

def bind(m):
 robot=instantiate_g1_robot_model(waist_location='lower_body',high_elbow_pose=False)
 names=robot.joint_names;assert len(names)==43
 rows=[]
 body_names=robot.supplemental_info.body_actuated_joints
 hand_parts=['thumb_0','thumb_1','thumb_2','index_0','index_1','middle_0','middle_1']
 lh=['left_hand_'+p+'_joint' for p in hand_parts];rh=['right_hand_'+p+'_joint' for p in hand_parts]
 motor_order=body_names[:22]+lh+body_names[22:]+rh
 previous=json.loads((OLD/'evidence/B_INTERFACE_RESULT.json').read_text())
 expected_native=[r['name'] for r in sorted(previous['joint_map'],key=lambda r:r['actuator_id'])]
 assert [m.actuator(i).name for i in range(m.nu)]==expected_native
 assert set(expected_native)==set(motor_order)
 q=robot.default_body_pose.copy();lower=robot.get_joint_group_indices('lower_body')
 q[lower]=np.array(CFG['default_angles'],np.float32)
 for i,name in enumerate(names):
  j=m.joint(name).id;a=m.actuator(name).id
  assert robot.dof_index(name)==i and int(m.actuator_trnid[a,0])==j
  assert np.array_equal(m.actuator_gear[a],np.array([1,0,0,0,0,0]))
  assert int(m.actuator_gaintype[a])==0 and int(m.actuator_biastype[a])==0 and m.actuator_gainprm[a,0]==1
  lo=max(float(m.jnt_range[j,0]),float(robot.lower_joint_limits[i]))
  hi=min(float(m.jnt_range[j,1]),float(robot.upper_joint_limits[i]))
  if name in body_names:
   b=body_names.index(name);kp=MAIN['MOTOR_KP'][b];kd=MAIN['MOTOR_KD'][b]
   lo=max(lo,float(MAIN['motor_pos_lower_limit_list'][b]));hi=min(hi,float(MAIN['motor_pos_upper_limit_list'][b]))
   vel=MAIN['motor_vel_limit_list'][b]
   group='lower' if b<15 else 'upper'
   if group=='upper':vel=min(vel,P['limits']['max_arm_speed_rps'])
  else:
   h=(lh if name.startswith('left_') else rh).index(name)
   kp=[2.,1,1,1,1,1,1][h];kd=[.5,.2,.2,.2,.2,.2,.2][h]
   vel=P['limits']['max_hand_speed_rps'];group='hand'
  effort=float(MAIN['motor_effort_limit_list'][a])
  native=float(min(-m.jnt_actfrcrange[j,0],m.jnt_actfrcrange[j,1])) if m.jnt_actfrclimited[j] else None
  assert lo<=hi and (lo<hi or (group=='hand' and lo==hi==0.))
  if group=='hand':assert q[i]==0 and lo<=0<=hi
  rows.append(dict(name=name,pin_q_index=i,joint=j,qpos=int(m.jnt_qposadr[j]),qvel=int(m.jnt_dofadr[j]),
   actuator=a,kp=float(kp),kd=float(kd),command_lower=lo,command_upper=hi,native_joint_range=m.jnt_range[j].tolist(),
   effort=effort,native_joint_effort=native,velocity_limit=float(vel),group=group))
 return robot,rows,q

def arrays(rows):
 return {k:np.array([r[k] for r in rows]) for k in ['qpos','qvel','actuator','kp','kd','command_lower','command_upper','effort','velocity_limit']} | {'hand_mask':np.array([r['group']=='hand' for r in rows])}

def validate_target(q,v):
 q=np.asarray(q)
 if q.shape!=(43,) or not np.isfinite(q).all():raise ValueError('target_shape_or_finite')
 if np.any(q<v['command_lower']) or np.any(q>v['command_upper']):raise ValueError('target_position_range')
 if np.any(q[v['hand_mask']]!=0.):raise ValueError('hand_target_not_zero')
 return q

def torque(d,target,v):
 validate_target(target,v)
 raw=v['kp']*(target-d.qpos[v['qpos']])-v['kd']*d.qvel[v['qvel']]
 clipped=np.clip(raw,-v['effort'],v['effort'])
 ctrl=np.empty(43);ctrl[v['actuator']]=clipped
 assert np.isfinite(ctrl).all()
 return ctrl,raw,clipped!=raw

def observation(d,v):
 return dict(q=d.qpos[v['qpos']].copy(),dq=d.qvel[v['qvel']].copy(),
  floating_base_pose=d.qpos[:7].copy(),floating_base_vel=d.qvel[:6].copy())

class ReferenceInput:
 def __init__(self,robot):
  self.body=[robot.dof_index(n) for n in robot.supplemental_info.body_actuated_joints]
  self.history=collections.deque(maxlen=6);self.previous=np.zeros(15,np.float32)
 def build(self,obs):
  defaults=np.zeros(29,np.float32);defaults[:15]=np.asarray(CFG['default_angles'],np.float32)
  rot=np.empty(9);mujoco.mju_quat2Mat(rot,obs['floating_base_pose'][3:7])
  single=np.concatenate([np.asarray(P['command'])*np.asarray(CFG['cmd_scale']),[P['height_command']],P['rpy_command'],
   obs['floating_base_vel'][3:6]*CFG['ang_vel_scale'],rot.reshape(3,3).T@np.array([0,0,-1]),
   (obs['q'][self.body]-defaults)*CFG['dof_pos_scale'],obs['dq'][self.body]*CFG['dof_vel_scale'],self.previous]).astype(np.float32)
  assert single.shape==(86,)
  self.history.append(single)
  while len(self.history)<6:self.history.appendleft(np.zeros(86,np.float32))
  return np.concatenate(list(self.history))[None,:]

class Runtime:
 def __init__(self,robot,label,cap,output_dir):
  self.output_dir=Path(output_dir).resolve();assert self.output_dir==R/'evidence'
  self.count=0;self.cap=cap;self.label=label;self.inputs=[];self.outputs=[];self.sessions={};self.weights=[]
  owner=self
  class Policy(G1GearWbcPolicy):
   def load_onnx_policy(self,path):
    opts=ort.SessionOptions();opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
    session=ort.InferenceSession(str(path),sess_options=opts,providers=['CPUExecutionProvider'])
    assert session.get_providers()==['CPUExecutionProvider']
    owner.sessions[Path(path).name]=session
    def infer(x):return torch.from_numpy(owner.call(session,x.cpu().numpy(),Path(path).name))
    return infer
  self.policy=Policy(robot,str(CFG_PATH),'policy/GR00T-WholeBodyControl-Balance.onnx,policy/GR00T-WholeBodyControl-Walk.onnx')
  self.policy.handle_keyboard_button(']')
  assert np.array_equal(self.policy.cmd,np.array(P['command'])) and self.policy.height_cmd==P['height_command']
  self.reference=ReferenceInput(robot)
 def call(self,s,x,purpose):
  assert self.count<self.cap
  x=np.asarray(x,np.float32);assert x.shape==(1,516) and np.isfinite(x).all()
  self.count+=1
  with (self.output_dir/f'B_{self.label}_FORWARDS.jsonl').open('a') as f:
   f.write(json.dumps(dict(call=self.count,purpose=purpose,shape=list(x.shape),provider='CPUExecutionProvider'))+'\n');f.flush()
  y=s.run(None,{s.get_inputs()[0].name:x})[0]
  assert y.shape==(1,15) and np.isfinite(y).all()
  self.inputs.append(x.copy());self.outputs.append(y.copy());self.weights.append(purpose)
  return y
 def action(self,obs,nominal,lower):
  expected=self.reference.build(obs);self.policy.set_observation(obs)
  error=float(np.max(np.abs(self.policy.obs_tensor.numpy()-expected)));assert error<=2e-6
  q,dq,tau=self.policy.get_action()['body_action']
  assert not np.any(dq) and not np.any(tau)
  assert np.array_equal(q,self.policy.action*CFG['action_scale']+np.array(CFG['default_angles'],np.float32))
  target=nominal.copy();target[lower]=q;self.reference.previous=self.policy.action.copy()
  return target,error,expected

def feet(m):
 sides={}
 for side in ['left','right']:
  b=m.body(side+'_ankle_roll_link').id
  ids=[g for g in range(m.ngeom) if int(m.geom_bodyid[g])==b and (m.geom_contype[g] or m.geom_conaffinity[g])]
  assert len(ids)==4 and all(m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE for g in ids)
  sides[side]=ids
 return sides

def measure(m,d,v,foot,base0,warning0):
 ground=set();contacts=[];bad=[];slip=0.;penetration=0.
 floor=m.geom('floor').id;allowed=set(foot['left']+foot['right'])
 jp=np.zeros((3,m.nv));jr=np.zeros((3,m.nv))
 for i in range(d.ncon):
  c=d.contact[i];a,b=int(c.geom1),int(c.geom2);force=np.zeros(6);mujoco.mj_contactForce(m,d,i,force)
  contacts.append(dict(g1=a,g2=b,dist=float(c.dist),pos=c.pos.tolist(),frame=c.frame.tolist(),force=force.tolist()))
  penetration=max(penetration,-float(c.dist));active=force[0]>1e-4 or c.dist < -1e-6
  if floor in (a,b):
   g=b if a==floor else a
   if g not in allowed and active:bad.append([a,b])
   if g in allowed and force[0]>1e-4:
    ground.add(g);mujoco.mj_jac(m,d,jp,jr,c.pos,int(m.geom_bodyid[g]))
    slip=max(slip,float(np.linalg.norm((jp@d.qvel)[:2])))
  elif active:bad.append([a,b])
 root=m.body('pelvis').id;limits=P['limits']
 excess=max(0.,float(np.max(v['command_lower']-d.qpos[v['qpos']]-limits['joint_limit_tolerance_rad'])),
  float(np.max(d.qpos[v['qpos']]-v['command_upper']-limits['joint_limit_tolerance_rad'])))
 return dict(tilt=float(np.arccos(np.clip(d.xmat[root].reshape(3,3)[2,2],-1,1))),
  xy_drift=float(np.linalg.norm(d.qpos[:2]-base0[:2])),z_drift=float(abs(d.qpos[2]-base0[2])),height=float(d.qpos[2]),
  slip=slip,penetration=penetration,both_feet_ground=bool(ground.intersection(foot['left']) and ground.intersection(foot['right'])),
  ground_any=bool(ground),ground_geoms=sorted(ground),unexpected_contacts=bad,joint_limit_excess=excess,
  base_linear_speed=float(np.linalg.norm(d.qvel[:3])),base_angular_speed=float(np.linalg.norm(d.qvel[3:6])),
  joint_velocity_excess=max(0.,float(np.max(np.abs(d.qvel[v['qvel']])-v['velocity_limit']))),
  generalized_speed=float(np.max(np.abs(d.qvel))),
  finite=bool(np.isfinite(d.qpos).all() and np.isfinite(d.qvel).all()),warning_changed=bool(np.any(d.warning.number!=warning0))),contacts

def gates(metric,gap):
 v=metric;l=P['limits']
 checks=dict(finite=v['finite'],warnings=not v['warning_changed'],tilt=v['tilt']<=l['max_tilt_rad'],
  xy_drift=v['xy_drift']<=l['max_xy_drift_m'],height=v['height']>=l['min_height_m'],z_drift=v['z_drift']<=l['max_z_drift_m'],
  penetration=v['penetration']<=l['max_penetration_m'],contacts=not v['unexpected_contacts'],
  joint_limits=v['joint_limit_excess']<=0,joint_speed=v['joint_velocity_excess']<=0,
  velocity_sanity=v['generalized_speed']<=l['max_generalized_speed_sanity'],ground_gap=gap<=l['max_ground_gap_seconds'])
 return [k for k,ok in checks.items() if not ok]

def state(m,d):
 s=np.empty(mujoco.mj_stateSize(m,SPEC));mujoco.mj_getState(m,d,s,SPEC)
 return dict(time=float(d.time),integration=s,qpos=d.qpos.copy(),qvel=d.qvel.copy(),
  actuator_force=d.actuator_force.copy(),qfrc_actuator=d.qfrc_actuator.copy())
