"""Grasp wrench geometry from saved contacts, with no force-closure claim."""
import numpy as np
import h5py
import mujoco
from .work import E, c, finish

def cross_matrix(v):
    x,y,z=v
    return np.array([[0.,-z,y],[z,0.,-x],[-y,x,0.]])

folder=E/'jobs/C_development_03/episode'
m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
obj=m.body('red_block').id;od=int(m.jnt_dofadr[m.joint('red_block_joint').id])
rows=[]
with h5py.File(folder/'TRACE.h5','r') as f:
 times=f['substep/time_before'][:]
 for seconds in [41.,42.,43.,44.,47.,50.,55.,60.,63.2475,65.,68.,70.,73.,76.,78.2475,78.4475,78.5125,78.515]:
  k=int(np.argmin(abs(times-seconds)))
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  mapping=[];contacts=[]
  for i,ct in enumerate(d.contact):
   bs=[int(m.geom_bodyid[g]) for g in [ct.geom1,ct.geom2]]
   if obj not in bs or ct.dist>0:continue
   other=ct.geom1 if bs[1]==obj else ct.geom2
   if not m.body(int(m.geom_bodyid[other])).name.startswith('right_hand'):continue
   lever=ct.pos-d.xipos[obj];block=np.vstack([np.eye(3),cross_matrix(lever)/.037])
   # condim3 supports point forces but no independent contact torque.
   if ct.dim>3:
    torque_axes=ct.frame.reshape(3,3)[:1 if ct.dim==4 else 3].T
    block=np.c_[block,np.vstack([np.zeros_like(torque_axes),torque_axes])]
   mapping.append(block)
   local=np.zeros(6);mujoco.mj_contactForce(m,d,i,local)
   contacts.append({'other_geom':m.geom(other).name,'point':ct.pos.tolist(),'condim':int(ct.dim),'local_force':local.tolist(),'friction':ct.friction.tolist()})
  if mapping:
   G=np.concatenate(mapping,axis=1);u,s,v=np.linalg.svd(G,full_matrices=True);rank=int(np.sum(s>1e-8))
   null=u[:,rank:];gravity=np.r_[m.body_mass[obj]*m.opt.gravity,np.zeros(3)]
   unopposed=null.T@gravity
   weak=u[:,-1];velocity=np.zeros(6);mujoco.mj_objectVelocity(m,d,mujoco.mjtObj.mjOBJ_BODY,obj,velocity,0);angular=velocity[:3]
   # SVD on force space ignores unilateral/friction bounds: full rank is only
   # a necessary geometric condition, not proof of force closure or strength.
   info={'rank':rank,'singular_values':s.tolist(),'minimum_singular_value':float(s[-1]) if len(s)==6 else 0.,
         'weakest_normalized_wrench_direction':weak.tolist(),'unresisted_gravity_projection_N':unopposed.tolist(),
         'weak_moment_axis_angular_speed_projection':float(weak[3:]@angular)}
  else:info={'rank':0,'singular_values':[]}
  rows.append({'row':k,'time':float(times[k]),'contacts':contacts,'wrench_geometry':info})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'moment_length_normalization_m':.037,'rows':rows,
        'scope':'Measured contact point force-to-object-wrench matrix rank and conditioning; ignores unilateral cones and actuator bounds; cannot certify grasp stability.',
        'production_accepted':False}
c.write(E/'C3_GRASP_WRENCH_GEOMETRY_R2.json',report);finish(report)
