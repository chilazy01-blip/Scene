"""Ideal point-contact cone and gravity equilibrium for five planned grasps."""
import numpy as np
import h5py
import mujoco
from scipy.optimize import linprog
from .work import E,c,finish
source=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(source/'TRACE.h5','r') as f:state=f['substep/integration_before'][15200]
arm=['right_'+n+'_joint' for n in ['shoulder_pitch','shoulder_roll','shoulder_yaw','elbow','wrist_roll','wrist_pitch','wrist_yaw']]
finger=['right_hand_'+n+'_joint' for n in ['thumb_0','thumb_1','thumb_2','index_0','index_1','middle_0','middle_1']]
arm_qa=[m.jnt_qposadr[m.joint(n).id] for n in arm];finger_qa=[m.jnt_qposadr[m.joint(n).id] for n in finger];finger_va=[m.jnt_dofadr[m.joint(n).id] for n in finger]
obj=m.body('red_block').id;weight=float(m.body_mass[obj]*9.81);plans=c.read(E/'D_PREGRASP_ROLL_TRIPOD_ENDPOINT_AND_PATH.json');records=[]
for candidate in [r for r in plans['candidates'] if r['static_candidate'] and r['coordinated_straight_path']['passed']]:
 mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);d.qpos[arm_qa]=candidate['arm_target_rad'];d.qpos[finger_qa]=candidate['finger_target_rad'];d.qvel[:]=0.;mujoco.mj_forward(m,d)
 rays=[];wrenches=[];indices=[];contacts=[]
 for ct in d.contact:
  b1,b2=[int(m.geom_bodyid[g]) for g in [ct.geom1,ct.geom2]]
  if obj not in [b1,b2] or ct.dist>0:continue
  other=ct.geom1 if b2==obj else ct.geom2;body=int(m.geom_bodyid[other])
  if not m.body(body).name.startswith('right_hand'):continue
  sign=1 if b2==obj else -1;frame=ct.frame.reshape(3,3);normal=sign*frame[0];lever=ct.pos-d.xipos[obj]
  i=len(contacts);contacts.append({'body':body,'geom':m.geom(other).name,'pos':ct.pos.copy(),'normal':normal,'mu':float(ct.friction[0])})
  for theta in np.linspace(0,2*np.pi,8,endpoint=False):
   force=normal+ct.friction[0]*(np.cos(theta)*frame[1]+np.sin(theta)*frame[2]);rays.append(force);wrenches.append(np.r_[force,np.cross(lever,force)/.037]);indices.append(i)
 W=np.array(wrenches).T;N=W.shape[1];rank=int(np.linalg.matrix_rank(W,tol=1e-8))
 b=np.array([0,0,weight,0,0,0]);equilibrium=linprog(np.ones(N),A_eq=W,b_eq=b,bounds=(0,None),method='highs')
 # A full-rank ray set with a strictly positive zero-wrench combination is
 # an ideal linearized force-closure certificate, not compliant dynamics.
 Aeq=np.r_[np.c_[W,np.zeros(6)],np.r_[np.ones(N),0.][None,:]];beq=np.r_[np.zeros(6),1.]
 Aineq=np.c_[-np.eye(N),np.ones(N)]
 closure=linprog(np.r_[np.zeros(N),-1.],A_ub=Aineq,b_ub=np.zeros(N),A_eq=Aeq,b_eq=beq,bounds=[(0,None)]*(N+1),method='highs')
 reactions=np.zeros(m.nv);forces=np.zeros((len(contacts),3));normal_sum=0.
 if equilibrium.success:
  for coefficient,ray,i in zip(equilibrium.x,rays,indices):forces[i]+=coefficient*ray;normal_sum+=float(coefficient)
  for contact,force in zip(contacts,forces):
   jp=np.zeros((3,m.nv));jr=np.zeros_like(jp);mujoco.mj_jac(m,d,jp,jr,contact['pos'],contact['body']);reactions+=jp.T@(-force)
  required=d.qfrc_bias[finger_va]-reactions[finger_va]
 else:required=None
 records.append({'palm_roll_change_deg':candidate['palm_roll_change_deg'],'palm_local_offset_m':candidate['palm_local_offset_m'],
                 'wrench_ray_rank':rank,'linearized_force_closure':bool(closure.success and rank==6 and closure.x[-1]>1e-9),
                 'strict_positive_coefficient_margin':float(closure.x[-1]) if closure.success else None,
                 'gravity_equilibrium_feasible':bool(equilibrium.success),'gravity_wrench_residual':float(np.max(abs(W@equilibrium.x-b))) if equilibrium.success else None,
                 'sum_normal_force_N':normal_sum if equilibrium.success else None,'finger_static_motor_torque_without_dry_friction_Nm':required.tolist() if required is not None else None,
                 'contact_forces_world_N':forces.tolist(),
                 'contacts':[{'geom':x['geom'],'pos':x['pos'].tolist(),'normal':x['normal'].tolist(),'mu':x['mu']} for x in contacts]})
report={'physics_steps':0,'policy_calls':0,'source_plan_sha256':c.sha(E/'D_PREGRASP_ROLL_TRIPOD_ENDPOINT_AND_PATH.json'),
        'object_weight_N':weight,'friction_cone_discretization':'8inscribed rays per point using retained model sliding friction;force-only contacts.',
        'cases':records,'scope':'Ideal instantaneous contact-cone and gravity equilibrium; ignores deformation/control error/dry friction uncertainty and is not dynamic or empirical physical calibration.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'D_TRIPOD_STATIC_FORCE_CERTIFICATES.json',report);finish(report)
