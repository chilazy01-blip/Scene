"""Gravity/PD equilibrium and measured self-contact clearance for left rest arm."""
import numpy as np
import h5py,mujoco
from scipy.optimize import least_squares
from .work import E,R,finish,c
m=mujoco.MjModel.from_binary_path(str(E/'jobs/C_development_01r/episode/MODEL.mjb'));d=mujoco.MjData(m)
names=['left_'+p+'_joint' for p in ['shoulder_pitch','shoulder_roll','shoulder_yaw','elbow','wrist_roll','wrist_pitch','wrist_yaw']]
jids=np.array([m.joint(n).id for n in names]);qa=m.jnt_qposadr[jids];va=m.jnt_dofadr[jids];kp=np.array([14.2506]*5+[16.7783]*2)
nominal=np.array([c.read(R/'branches/A/source/model_config.json')['default_joint_pos'][n] for n in names])
pairs=[(m.geom('g2_col').id,m.geom(n).id) for n in ['left_hand_thumb_2_link_col','gripper0_left_g0_col','gripper0_left_g1_col']]
records=[]
for label,folder,times in [('stationary',E/'jobs/C_development_01r/episode',[.2,.84,4.,50.,150.]),('walking',R/'jobs/A_target_02/episode',[13.5,13.8,14.2,20.,30.,58.71])]:
 with h5py.File(folder/'TRACE.h5','r') as f:
  for sec in times:
   k=int(round(sec/.0025))-1;original=f['substep/qpos'][k]
   for elbow in [.6,.56,.54]:
    command=nominal.copy();command[3]=elbow
    def residual(q):
     d.qpos[:]=original;d.qpos[qa]=q;d.qvel[:]=0;mujoco.mj_forward(m,d)
     return kp*(command-q)-d.qfrc_bias[va]
    result=least_squares(residual,np.clip(original[qa],m.jnt_range[jids,0]+1e-8,m.jnt_range[jids,1]-1e-8),bounds=(m.jnt_range[jids,0],m.jnt_range[jids,1]),max_nfev=60,ftol=1e-10,xtol=1e-10,gtol=1e-10)
    res=residual(result.x);distances=[mujoco.mj_geomDistance(m,d,a,b,.10,None) for a,b in pairs]
    records.append({'source':label,'time':sec,'elbow_command_rad':elbow,'residual_max_Nm':float(np.max(abs(res))),'equilibrium_joint_positions':result.x.tolist(),'hand_thigh_clearance_m':list(map(float,distances)),'minimum_clearance_m':float(min(distances))})
report={'physics_steps':0,'policy_calls':0,'joint_names':names,'nominal_source_commands':nominal.tolist(),'source_PD_gains':kp.tolist(),'records':records,
        'counterfactual_scope':'Gravity-balanced arm only at saved base/leg poses; contact forces excluded from equilibrium so penetration is exposed, not supported by thigh contact.',
        'dynamic_admission':False,'plant_and_actuator_unchanged':True,'production_accepted':False}
c.write(E/'STOW_EQUILIBRIUM_STATIC_ANALYSIS.json',report);finish(report)
