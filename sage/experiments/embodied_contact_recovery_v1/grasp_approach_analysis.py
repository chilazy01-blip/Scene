"""Inspect actual hand/table onset and static escape/lift geometry without integration."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work))
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r3 import install
install('A','gain_translation',work/'static_interface')
import run
from ik.sim import ArmIK6
folder=E/'jobs/pipeline_initial_window_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
controller=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,controller)
hands=[g for g in range(m.ngeom) if m.geom_contype[g] and 'right_hand' in m.body(int(m.geom_bodyid[g])).name]
table=m.geom('table_top').id

def bounds():
 points=[]
 for g in hands:
  mesh=int(m.geom_dataid[g]);assert m.geom_type[g]==mujoco.mjtGeom.mjGEOM_MESH
  begin=int(m.mesh_vertadr[mesh]);verts=m.mesh_vert[begin:begin+int(m.mesh_vertnum[mesh])]
  points.extend(d.geom_xpos[g]+verts@d.geom_xmat[g].reshape(3,3).T)
 points=np.asarray(points);return points.min(0),points.max(0)
with h5py.File(folder/'TRACE.h5','r') as f:
 contacts=f['contacts/rows'][:];bad=[r for r in contacts if table in map(int,r[1:3]) and any(int(g) in hands for g in r[1:3])]
 first=int(bad[0][0]);start=((first-200)//8)*8
 policy=f['policy/walker_onnx'];pr=policy['physics_row'][:];inp=policy['input'][next(iter(policy['input']))][:].reshape(len(pr),-1)
 rows=[]
 for k in sorted(set([1600,2000,start,first,2800,3200,3600,3999])):
  mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d);lo,hi=bounds()
  pi=min(len(pr)-1,max(0,int(np.searchsorted(pr,k,side='right')-1)))
  rows.append({'row':k,'time':float(d.time),'base_xyz':d.qpos[:3].tolist(),'base_velocity':d.qvel[:3].tolist(),'walker_command':inp[pi,-3:].tolist(),'palm_position':d.site_xpos[ik.site_id].tolist(),'hand_bounds_min':lo.tolist(),'hand_bounds_max':hi.tolist(),'arm_actual':d.qpos[ik.qpos_idx].tolist(),'arm_target':f['interpolation/requested'][k][controller.right_arm_indices].tolist(),'finger_actual':{m.actuator(a).name:float(d.qpos[m.jnt_qposadr[m.actuator_trnid[a,0]]]) for a,_ in controller.right_finger_actuators},'table_contacts':[{'pair':[m.geom(x.geom1).name,m.geom(x.geom2).name],'dist':float(x.dist)} for x in d.contact if table in (x.geom1,x.geom2)]})
 mujoco.mj_setState(m,d,f['substep/integration_before'][start],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
 initial=d.qpos.copy();lo,hi=bounds();palm=d.site_xpos[ik.site_id].copy();rot=d.site_xmat[ik.site_id].reshape(3,3).copy();center=d.geom_xpos[table].copy();half=m.geom_size[table].copy();edge=center-half;top=float(center[2]+half[2])
 # Robot approaches the near-x edge in this bound development geometry.
 escape_dx=min(0.,float(edge[0]-.025-hi[0]));retreat=palm+np.array([escape_dx,0,0]);rise=retreat.copy();rise[2]+=max(0.,top+.045-lo[2])
 plans=[]
 for name,target in [('retreat_clear',retreat),('vertical_raise',rise)]:
  begin=d.site_xpos[ik.site_id].copy();segments=max(1,int(np.ceil(np.linalg.norm(target-begin)/.008)));path=[]
  for alpha in np.linspace(0,1,segments+1)[1:]:
   waypoint=begin+alpha*(target-begin);q,res,rot_error=ik.solve(d,waypoint,rot,iters=160)
   d.qpos[ik.qpos_idx]=q;mujoco.mj_forward(m,d)
   hand_contacts=[{'pair':[m.geom(x.geom1).name,m.geom(x.geom2).name],'dist':float(x.dist)} for x in d.contact if table in (x.geom1,x.geom2) and any(g in hands for g in [x.geom1,x.geom2])]
   path.append({'q':q.tolist(),'palm_goal':waypoint.tolist(),'position_residual_m':float(res),'rotation_residual':float(rot_error),'table_contacts':hand_contacts})
  plans.append({'stage':name,'goal':target.tolist(),'waypoints':path,'max_position_residual_m':max(x['position_residual_m'] for x in path),'no_table_contact':not any(x['table_contacts'] for x in path)})
report={'physics_steps':0,'source':str(folder),'source_trace_sha256':c.sha(folder/'TRACE.h5'),'first_table_hand_row':first,'saved_start_row':start,'saved_start_time_s':start*.0025,'snapshots':rows,'static_escape_then_raise':plans,'table_top_z':top,'dynamic_admission':False,'all_work_on_scratch_state':True}
c.write(E/'GRASP_APPROACH_CAUSAL_ANALYSIS.json',report);finish(report)
