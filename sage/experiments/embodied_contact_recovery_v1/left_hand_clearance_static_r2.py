"""Geometric clearance at every saved C3 left-hand/thigh contact state."""
import numpy as np,h5py,mujoco
from scipy.spatial import ConvexHull
from .work import E,c,finish
folder=E/'jobs/C_development_03/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);thigh=m.geom('g2_col').id
hands=[g for g in range(m.ngeom) if m.geom_contype[g] and 'left_hand' in m.body(int(m.geom_bodyid[g])).name]
meshes={}
for g in [thigh,*hands]:
 if m.geom_type[g]==mujoco.mjtGeom.mjGEOM_BOX:
  import itertools
  v=np.array(list(itertools.product([-1.,1.],repeat=3)))*m.geom_size[g]
 elif m.geom_type[g]==mujoco.mjtGeom.mjGEOM_MESH:
  mesh=int(m.geom_dataid[g]);begin=int(m.mesh_vertadr[mesh]);v=m.mesh_vert[begin:begin+int(m.mesh_vertnum[mesh])].copy()
 else:raise ValueError(('unsupported geometry',m.geom(g).name,int(m.geom_type[g])))
 h=ConvexHull(v);meshes[g]=(v[h.vertices],h.equations[:,:3])
def separated_gap(g,h):
 vg,ng=meshes[g];vh,nh=meshes[h];rg=d.geom_xmat[g].reshape(3,3);rh=d.geom_xmat[h].reshape(3,3)
 vg=vg@rg.T+d.geom_xpos[g];vh=vh@rh.T+d.geom_xpos[h];axes=np.r_[ng@rg.T,nh@rh.T]
 a=vg@axes.T;b=vh@axes.T
 return float(np.max(np.maximum(b.min(0)-a.max(0),a.min(0)-b.max(0))))
with h5py.File(folder/'TRACE.h5','r') as f:
 contacts=f['contacts/rows'][:];keys=sorted({int(r[0]) for r in contacts if thigh in r[1:3] and any(int(g) in hands for g in r[1:3])});states=[f['substep/integration_before'][k] for k in keys]
assert keys
qa=m.jnt_qposadr[m.joint('left_elbow_joint').id];rows=[]
for offset in [0.,-.05,-.10,-.15,-.20,-.25]:
 gap=1.;closest=None;forbidden=0;api_zero=0
 for k,state in zip(keys,states):
  mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);d.qpos[qa]+=offset;mujoco.mj_forward(m,d)
  for g in hands:
   value=separated_gap(thigh,g)
   if value<gap:gap=value;closest={'row':k,'geom':m.geom(g).name}
   api_zero+=int(mujoco.mj_geomDistance(m,d,thigh,g,.1,None)==0.)
  forbidden+=sum(thigh in [ct.geom1,ct.geom2] and any(g in hands for g in [ct.geom1,ct.geom2]) and ct.dist<0 for ct in d.contact)
 rows.append({'left_elbow_offset_rad':offset,'conservative_separating_axis_gap_m':gap,'worst':closest,'penetrating_contact_count':int(forbidden),'mj_geomDistance_zero_count':api_zero})
report={'physics_steps':0,'policy_calls':0,'source':str(folder),'saved_contact_state_count':len(states),'candidates':rows,'positive_gap_is_a_certified_projection_separation_lower_bound':True,'negative_gap_is_not_an_exact_penetration_depth':True,'dynamic_admission':False,'method_C_remains_closed':True,'production_accepted':False}
c.write(E/'LEFT_HAND_CLEARANCE_STATIC.json',report);finish(report)
