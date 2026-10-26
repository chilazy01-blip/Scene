"""Validate all sampled intermediate rigid-grasp configurations of a D plan."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
plans=c.read(E/'D_LOW_PRELOAD_UPRIGHT_STATIC_REGRESSION.json')['saved_pre_place_cases']
folder=E/'jobs/grasp_friction_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
names=['right_'+n+'_joint' for n in ['shoulder_pitch','shoulder_roll','shoulder_yaw','elbow','wrist_roll','wrist_pitch','wrist_yaw']]
qa=np.array([m.jnt_qposadr[m.joint(n).id] for n in names]);va=np.array([m.jnt_dofadr[m.joint(n).id] for n in names]);aids=np.array([m.actuator(n).id for n in names]);obj=m.body('red_block').id;oa=m.jnt_qposadr[m.joint('red_block_joint').id];sid=m.site('right_palm').id
results=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 for item in plans:
  mujoco.mj_setState(m,d,f['substep/integration_before'][item['source_row']],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  q=d.qpos.copy();wrist=d.site_xmat[sid].reshape(3,3).copy();relative=wrist.T@(d.xpos[obj]-d.site_xpos[sid]);relative_R=wrist.T@d.xmat[obj].reshape(3,3);target=np.asarray(item['result']['variables']);path=[]
  for fraction in np.linspace(0,1,81):
   d.qpos[:]=q;d.qvel[:]=0.;d.qpos[qa]=q[qa]+fraction*(target[:-2]-q[qa]);d.qpos[:2]=q[:2]+fraction*target[-2:]
   mujoco.mj_kinematics(m,d);rw=d.site_xmat[sid].reshape(3,3);pos=d.site_xpos[sid]+rw@relative;rot=rw@relative_R
   d.qpos[oa:oa+3]=pos;mujoco.mju_mat2Quat(d.qpos[oa+3:oa+7],rot.ravel());mujoco.mj_forward(m,d)
   forbidden=[];pen=0.
   for ct in d.contact:
    bs=[m.body(int(m.geom_bodyid[g])).name for g in [ct.geom1,ct.geom2]];gn=[m.geom(g).name for g in [ct.geom1,ct.geom2]]
    foot='ground' in gn and any('ankle_roll' in b for b in bs);held='red_block' in bs and any('right_hand' in b for b in bs)
    robot=any('hand' in b or b.endswith('_link') for b in bs)
    if robot and not (foot or held) and ct.dist<0:forbidden.append({'geoms':gn,'penetration_m':float(-ct.dist)})
    pen=max(pen,float(-ct.dist))
   torque=np.minimum(d.qfrc_bias[va]-m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1]-d.qfrc_bias[va])
   path.append({'fraction':float(fraction),'object_xyz':pos.tolist(),'object_tilt_deg':float(np.degrees(np.arccos(np.clip(rot[2,2],-1,1)))),'maximum_penetration_m':pen,'forbidden':forbidden,'arm_static_torque_margin_Nm':float(min(torque))})
  results.append({'source_row':item['source_row'],'path':path,'static_path_constraints_passed':all(not r['forbidden'] and r['maximum_penetration_m']<=.01 and r['arm_static_torque_margin_Nm']>=0 for r in path)})
report={'physics_steps':0,'policy_calls':0,'method':'D_object_pose_planning','paths':results,'scope':'81 static intermediate samples each, rigid measured object-to-palm transform, base translations are planning variables only; no runtime teleport or closed-loop dynamic proof.','dynamic_admission':False,'production_accepted':False}
c.write(E/'D_UPRIGHT_PATH_STATIC_VALIDATION.json',report);finish(report)
