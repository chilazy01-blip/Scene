"""Continuous policy checkpoint and atomic Body29/Hand14 native PD consumer."""
from .runtime import *
from .native_hand import NativeHand

class NamedAction:
 def __init__(self,m,robot,rows):
  self.rows=rows;self.v=arrays(rows)
  self.body_names=list(robot.supplemental_info.body_actuated_joints)
  self.body=np.array([robot.dof_index(n) for n in self.body_names])
  parts=['thumb_0','thumb_1','thumb_2','index_0','index_1','middle_0','middle_1']
  self.hand_names=[f'{side}_hand_{p}_joint' for side in ['left','right'] for p in parts]
  self.hand=np.array([robot.dof_index(n) for n in self.hand_names])
  self.native=NativeHand(m,self.hand_names,rows)
  self.v['command_lower'][self.hand]=self.native.lower
  self.v['command_upper'][self.hand]=self.native.upper
  self.amplitude=np.where(abs(self.native.lower)>abs(self.native.upper),self.native.lower,self.native.upper)*.1
 def packet(self,body,hand,time):
  return dict(body_names=self.body_names,hand_names=self.hand_names,body=np.asarray(body).tolist(),hand=np.asarray(hand).tolist(),units='rad',coordinate_frame='native_mjcf_joint',time=float(time))
 def validate(self,data,packet):
  if set(packet)!={'body_names','hand_names','body','hand','units','coordinate_frame','time'}:raise ValueError('packet_fields')
  if packet['body_names']!=self.body_names:raise ValueError('body_joint_order')
  if not np.isfinite(packet['time']) or abs(packet['time']-data.time)>1e-10:raise ValueError('command_time')
  hand=self.native.validate(packet['hand'],names=packet['hand_names'],units=packet['units'],coordinate_frame=packet['coordinate_frame'])
  body=np.asarray(packet['body'],float)
  if body.shape!=(29,) or not np.isfinite(body).all():raise ValueError('body_shape_finite')
  if np.any(body<self.v['command_lower'][self.body]) or np.any(body>self.v['command_upper'][self.body]):raise ValueError('body_range')
  target=np.empty(43);target[self.body]=body;target[self.hand]=hand
  return target
 def command(self,data,packet):
  target=self.validate(data,packet)
  raw=self.v['kp']*(target-data.qpos[self.v['qpos']])-self.v['kd']*data.qvel[self.v['qvel']]
  if not np.isfinite(raw).all():raise ValueError('nonfinite_PD')
  ctrl=np.empty(43);ctrl[self.v['actuator']]=np.clip(raw,-self.v['effort'],self.v['effort'])
  data.ctrl[:]=ctrl
  return target,raw,ctrl,(abs(raw)>self.v['effort'])
 def path(self,elapsed):
  if elapsed<0 or elapsed>4+1e-10:raise ValueError('path_time')
  q=np.zeros(14);side=min(int(elapsed//2),1);t=elapsed-2*side
  smooth=lambda x:x*x*(3-2*x)
  if t<.75:s=smooth(t/.75)
  elif t<1:s=1.
  elif t<1.75:s=1-smooth((t-1)/.75)
  else:s=0.
  q[side*7:side*7+7]=s*self.amplitude[side*7:side*7+7]
  return q

def restore_integration(m,d,saved):
 mujoco.mj_setState(m,d,saved,SPEC);mujoco.mj_forward(m,d);mujoco.mj_setState(m,d,saved,SPEC)
 assert np.array_equal(state(m,d)['integration'],saved)

def restore_saved_policy(runtime,history_input,action,n_observations,observation_at_last,previous_action):
 """Derive absent gait cache via exact official recurrence, without ONNX/physics."""
 p=runtime.policy
 history=np.asarray(history_input,np.float32).reshape(6,86)
 assert n_observations>=6 and history.shape==(6,86)
 assert np.array_equal(history[-1,-15:],previous_action)
 p.cmd=np.array(P['command'],float);p.height_cmd=P['height_command'];p.roll_cmd,p.pitch_cmd,p.yaw_cmd=P['rpy_command']
 p.use_policy_action=True;p.use_teleop_policy_cmd=False;p.counter=0
 p.gait_indices=torch.zeros(1,dtype=torch.float32)
 for _ in range(n_observations-1):p.gait_indices=torch.remainder(p.gait_indices+.02*p.freq_cmd,1.)
 p.action=np.asarray(previous_action,np.float32).copy()
 single,_=p.compute_observation(observation_at_last)
 assert np.max(abs(single-history[-1]))<=2e-6
 p.observation=observation_at_last
 p.obs_history=collections.deque([x.copy() for x in history],maxlen=6)
 p.obs_buffer=np.concatenate(history).copy();p.obs_tensor=torch.from_numpy(p.obs_buffer).unsqueeze(0)
 p.action=np.asarray(action,np.float32).copy()
 runtime.reference.history=collections.deque([x.copy() for x in history],maxlen=6)
 runtime.reference.previous=p.action.copy()

def checkpoint(runtime,integration,last_target,next_step):
 p=runtime.policy
 return dict(integration=integration.copy(),history=np.asarray(p.obs_history),previous_action=p.action.copy(),
  gait_indices=p.gait_indices.numpy().copy(),foot_indices=p.foot_indices.numpy().copy(),clock_inputs=p.clock_inputs.numpy().copy(),
  obs_buffer=p.obs_buffer.copy(),last_target=last_target.copy(),next_step=np.array(next_step),
  cmd=np.asarray(p.cmd),height=np.array(p.height_cmd),rpy=np.array([p.roll_cmd,p.pitch_cmd,p.yaw_cmd]),freq=np.array(p.freq_cmd),
  counter=np.array(p.counter),use_policy_action=np.array(p.use_policy_action),use_teleop=np.array(p.use_teleop_policy_cmd),target_dof_pos=np.asarray(p.target_dof_pos),
  **{'observation_'+k:v.copy() for k,v in p.observation.items()})

def load_checkpoint(runtime,m,d,z):
 restore_integration(m,d,z['integration']);p=runtime.policy
 p.obs_history=collections.deque([x.copy() for x in z['history']],maxlen=6)
 p.obs_buffer=z['obs_buffer'].copy();p.obs_tensor=torch.from_numpy(p.obs_buffer).unsqueeze(0)
 assert np.array_equal(p.obs_buffer,np.concatenate(p.obs_history))
 p.action=z['previous_action'].copy()
 for field in ['gait_indices','foot_indices','clock_inputs']:setattr(p,field,torch.from_numpy(z[field].copy()))
 p.cmd=z['cmd'].copy();p.height_cmd=float(z['height']);p.roll_cmd,p.pitch_cmd,p.yaw_cmd=z['rpy'];p.freq_cmd=float(z['freq']);p.counter=int(z['counter'])
 p.use_policy_action=bool(z['use_policy_action']);p.use_teleop_policy_cmd=bool(z['use_teleop']);p.target_dof_pos=z['target_dof_pos'].copy()
 p.observation={k.removeprefix('observation_'):z[k].copy() for k in z if k.startswith('observation_')}
 runtime.reference.history=collections.deque([x.copy() for x in z['history']],maxlen=6);runtime.reference.previous=p.action.copy()
 assert int(z['next_step'])==800 and int(z['next_step'])%P['decimation']==0
 return z['last_target'].copy(),int(z['next_step'])
