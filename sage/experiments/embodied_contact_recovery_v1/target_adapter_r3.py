"""Target plant and explicit source-input/current-actuator interface translation.
No physical geometry, inertia, gains, friction or torque limits are changed here.
"""
from runtime import R,read,write,sha
from pathlib import Path
import os,json
import numpy as np,mujoco
TARGET=R/'shared/target/MODEL.xml'
CURRENT=read(R.parent/'generated/GLOCAL_NEW/package_r2/CONTRACT.json')

def full_mass(model,data):
 matrix=np.empty((model.nv,model.nv))
 try:mujoco.mj_fullM(model,data,matrix)
 except TypeError:mujoco.mj_fullM(model,matrix,data.qM)
 return matrix

class TargetActuation:
 def __init__(self,model,controller,profile,branch):
  self.model=model;self.ctrl=controller;self.profile=profile;self.branch=branch;self.names=CURRENT['joint_names'];self.qmap=np.array([model.jnt_qposadr[model.joint(n).id] for n in self.names],int);self.dofs=np.array([model.jnt_dofadr[model.joint(n).id] for n in self.names],int);self.aids=np.array([model.actuator(n).id for n in self.names]);self.limits=np.array([model.jnt_range[model.joint(n).id] for n in self.names]);self.groups=CURRENT['inspection']['groups'];self.parts={};self.last={}
  for part,ids in [('legs',self.groups['lower_body'][:12]),('torso',self.groups['lower_body'][12:]),('left',self.groups['left_arm']),('right',self.groups['right_arm'])]:
   p=CURRENT['inspection']['controllers'][part]['attributes'];self.parts[part]=(np.array(ids),np.array(p['kp']),np.array(p['kd']))
  self.source_kp=controller.kp.copy();self.source_kd=controller.kd.copy();self.by_source={n:i for i,n in enumerate(controller.joint_names)}
 def apply(self,data,target_pos):
  m=self.model;mujoco.mj_forward(m,data);M=full_mass(m,data);q=data.qpos[self.qmap];v=data.qvel[self.dofs];issued=q.copy();desired=q.copy();tau=np.zeros(m.nu)
  for i,name in enumerate(self.names):
   if name in self.by_source:desired[i]=np.clip(target_pos[self.by_source[name]],*m.jnt_range[m.joint(name).id])
  for part,(ids,kp,kd) in self.parts.items():
   dofs=self.dofs[ids];aids=self.aids[ids]
   if self.profile.startswith('gain_translation'):
    si=np.array([self.by_source[self.names[i]] for i in ids]);source_pd=self.source_kp[si]*(desired[ids]-q[ids])-self.source_kd[si]*v[ids]
    # Equivalent target for the retained target controller law. Arms/torso already compensate gravity.
    requested_torque=source_pd+(data.qfrc_bias[dofs] if part in ('left','right') and self.branch=='A' else 0)
    accel=source_pd if part=='legs' else np.linalg.solve(M[np.ix_(dofs,dofs)],requested_torque-data.qfrc_bias[dofs])
    issued[ids]=q[ids]+(accel+kd*v[ids])/kp
   else:issued[ids]=desired[ids]
   issued[ids]=np.clip(issued[ids],self.limits[ids,0],self.limits[ids,1])
   pd=kp*(issued[ids]-q[ids])-kd*v[ids]
   actual=pd if part=='legs' else M[np.ix_(dofs,dofs)]@pd+data.qfrc_bias[dofs]
   tau[aids]=np.clip(actual,m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1])
  hands=self.groups['left_hand']+self.groups['right_hand'];tau[self.aids[hands]]=0.
  for act_id,closed in self.ctrl.right_finger_actuators:tau[act_id]=closed if self.ctrl.grip_closed else 0.
  data.ctrl[:]=tau;self.last={'desired_position':desired.copy(),'issued_target':issued.copy(),'body_torque':tau.copy()}
  import instrument
  if getattr(instrument,'ACTIVE_TRACE',None) is not None:
   def issued_positions():
    p=issued.copy();p[hands]=data.ctrl[self.aids[hands]];return p
   instrument.ACTIVE_TRACE.position_provider=issued_positions
   instrument.ACTIVE_TRACE.nominal_provider=lambda:desired.copy()

def install(branch,profile,record_folder):
 global TARGET
 TARGET=Path(os.environ.get('CONTACT_MODEL_XML',str(R/'shared/target'/('MODEL_B.xml' if branch=='B' else 'MODEL.xml'))))
 assert profile in ['direct_current_gains','gain_translation','gain_translation_named_upper']
 import run
 source=R/'branches'/branch/'source';work=Path(record_folder)/'target_runtime';work.mkdir(parents=True,exist_ok=True)
 (work/'scene.xml').symlink_to(TARGET)
 for name in ['model_config.json','walker.onnx','walker.onnx.data','croucher.onnx','croucher.onnx.data','rotator.onnx','rotator.onnx.data','right_reacher.onnx','right_reacher.onnx.data']:(work/name).symlink_to(source/name)
 source_model=mujoco.MjModel.from_xml_path(str(source/'scene.xml'));initial=mujoco.MjData(source_model);config=read(source/'model_config.json')
 for name,value in config['default_joint_pos'].items():
  if name in config['joint_names']:initial.qpos[7+config['joint_names'].index(name)]=value
 source_observation={n:source_model.joint(int(np.flatnonzero(source_model.jnt_qposadr==7+i)[0])).name for i,n in enumerate(config['joint_names'])}
 target_model=mujoco.MjModel.from_xml_path(str(TARGET))
 raw_initial_angles={n:float(initial.qpos[source_model.jnt_qposadr[source_model.joint(n).id]]) for n in CURRENT['joint_names']}
 initial_angles={n:float(np.clip(v,*target_model.jnt_range[target_model.joint(n).id])) for n,v in raw_initial_angles.items()}
 if (branch=='B' and profile=='gain_translation_named_upper') or (branch=='A' and os.environ.get('CONTACT_NAMED_INITIAL','0')=='1'):
  initial_angles={n:float(np.clip(config['default_joint_pos'].get(n,0.),*target_model.jnt_range[target_model.joint(n).id])) for n in CURRENT['joint_names']}
 if os.environ.get('CONTACT_STOW_JOINT'):
  name=os.environ['CONTACT_STOW_JOINT'];value=initial_angles[name]+float(os.environ['CONTACT_STOW_OFFSET'])
  assert target_model.jnt_range[target_model.joint(name).id,0]<=value<=target_model.jnt_range[target_model.joint(name).id,1]
  initial_angles[name]=value
 original_mapping=run.G1Controller._build_joint_mappings
 def mappings(ctrl):
  original_mapping(ctrl)
  # Preserve actual upstream observation contents, including the legacy seven body-policy observation slots.
  for label,physical in source_observation.items():
   ctrl.joint_qpos_indices[label]=int(ctrl.model.jnt_qposadr[ctrl.model.joint(physical).id]);ctrl.joint_qvel_indices[label]=int(ctrl.model.jnt_dofadr[ctrl.model.joint(physical).id])
 run.G1Controller._build_joint_mappings=mappings
 def apply(ctrl,target):
  if not hasattr(ctrl,'_target_actuation'):ctrl._target_actuation=TargetActuation(ctrl.model,ctrl,profile,branch)
  ctrl._target_actuation.apply(ctrl.data,target)
 run.G1Controller.apply_pd_control=apply
 def preserve_armature(*a,**kw):pass
 run.set_armature=preserve_armature;run.SCRIPT_DIR=work
 def initialize(m,d):
  for name,value in initial_angles.items():d.qpos[m.jnt_qposadr[m.joint(name).id]]=value
  m.opt.timestep=.0025;mujoco.mj_forward(m,d)
 if branch=='A':
  from ik import sim,pipeline
  sim.SCRIPT_DIR=work;sim.set_armature=preserve_armature;sim.DECIMATION=8;pipeline.MONITOR_EVERY=20
  original_build=sim.build_sim
  def build(*a,**kw):
   m,d,c=original_build(*a,**kw);initialize(m,d);return m,d,c
  sim.build_sim=build
  # Native target upper-body controller already adds qfrc_bias, avoiding duplicate gravity compensation.
  sim.ArmIK6.sag_correction=lambda ik,data,q_star=None:np.zeros(len(ik.act_idx))
 else:
  import sim
  sim.SCRIPT_DIR=work;sim.set_armature=preserve_armature
  original_init=sim.G1PickPlaceEnv.__init__;original_reset=sim.G1PickPlaceEnv._reset_robot_pose
  def init(env,*a,**kw):
   original_init(env,*a,**kw);env.model.opt.timestep=.0025;env.cfg.control_decimation=8;env.control_dt=.02
  def reset(env):original_reset(env);initialize(env.model,env.data)
  sim.G1PickPlaceEnv.__init__=init;sim.G1PickPlaceEnv._reset_robot_pose=reset
  if profile=='gain_translation_named_upper':
   def arm_positions(ctrl):
    return np.array([ctrl.data.qpos[ctrl.model.jnt_qposadr[ctrl.model.joint(n).id]]-ctrl.arm_default_pos[i] for i,n in enumerate(ctrl.right_arm_joint_names)],dtype=np.float32)
   def arm_velocities(ctrl):
    return np.array([ctrl.data.qvel[ctrl.model.jnt_dofadr[ctrl.model.joint(n).id]] for n in ctrl.right_arm_joint_names],dtype=np.float32)
   run.G1Controller._get_arm_joint_positions=arm_positions;run.G1Controller._get_arm_joint_velocities=arm_velocities
   original_obs=sim.G1PickPlaceEnv._get_obs
   def observations(env,metrics):
    obs=original_obs(env,metrics);ctrl=env.controller
    for i,n in enumerate(ctrl.joint_names):
     jid=env.model.joint(n).id;obs['proprio'][9+i]=env.data.qpos[env.model.jnt_qposadr[jid]]-ctrl.default_joint_pos[i];obs['proprio'][38+i]=env.data.qvel[env.model.jnt_dofadr[jid]]
    return obs
   sim.G1PickPlaceEnv._get_obs=observations
 report={'profile':profile,'model_sha256':sha(TARGET),'current_actuator_contract_sha256':sha(R.parent/'generated/GLOCAL_NEW/package_r2/CONTRACT.json'),'source_observation_physical_joint':source_observation,'initial_angles_by_physical_joint':initial_angles,'command_period_s':.02,'dt':.0025,'current_gains_and_limits_preserved':True,'source_armature_overwrite_disabled':True,'duplicate_arm_gravity_compensation_removed':True,'all_reference_changes_logged':True,'source_legacy_observation_layout_preserved_explicitly':True,'raw_source_initial_angles':raw_initial_angles,'initial_joint_limits_enforced':True,'issued_reference_joint_limits_enforced':True,'upper_and_reacher_named_joint_fix':profile=='gain_translation_named_upper','left_arm_gravity_feedforward':branch=='A','named_initialization':os.environ.get('CONTACT_NAMED_INITIAL','0')=='1','production_accepted':False}
 write(Path(record_folder)/'ADAPTER.json',report);return report
