"""Measured hand-envelope clearance before the final near-x tabletop approach."""
import numpy as np
import mujoco

def hand_bounds(model,data):
 points=[]
 for g in range(model.ngeom):
  if not model.geom_contype[g] or 'right_hand' not in model.body(int(model.geom_bodyid[g])).name:continue
  kind=model.geom_type[g];rot=data.geom_xmat[g].reshape(3,3);center=data.geom_xpos[g];size=model.geom_size[g]
  if kind==mujoco.mjtGeom.mjGEOM_MESH:
   mesh=int(model.geom_dataid[g]);begin=int(model.mesh_vertadr[mesh]);verts=model.mesh_vert[begin:begin+int(model.mesh_vertnum[mesh])];points.extend(center+verts@rot.T)
  else:
   if kind==mujoco.mjtGeom.mjGEOM_BOX:extent=abs(rot)@size
   elif kind==mujoco.mjtGeom.mjGEOM_SPHERE:extent=np.ones(3)*size[0]
   elif kind==mujoco.mjtGeom.mjGEOM_CAPSULE:extent=np.ones(3)*size[0]+abs(rot[:,2])*size[1]
   elif kind==mujoco.mjtGeom.mjGEOM_CYLINDER:extent=np.sqrt(np.maximum(0,1-rot[:,2]**2))*size[0]+abs(rot[:,2])*size[1]
   else:raise ValueError(('unsupported hand geometry',model.geom(g).name,int(kind)))
   points.extend([center-extent,center+extent])
 points=np.asarray(points);return points.min(0),points.max(0)

def clearance_goals(runner):
 m,d=runner.model,runner.data;palm,rot=runner.palm_pose();lo,hi=hand_bounds(m,d);g=m.geom('table_top').id
 assert np.max(abs(d.geom_xmat[g].reshape(3,3)-np.eye(3)))<1e-8,'near_x_approach_requires_axis_aligned_table'
 center=d.geom_xpos[g];half=m.geom_size[g];edge=center-half;top=float(center[2]+half[2])
 assert palm[0]<center[0],'near_x_approach_required'
 retreat=palm+np.array([min(0.,float(edge[0]-.025-hi[0])),0,0]);rise=retreat.copy();rise[2]+=max(0.,top+.045-lo[2])
 return retreat,rise,rot,top

def raise_clear(runner):
 import instrument
 retreat,rise,rot,top=clearance_goals(runner);tr=instrument.ACTIVE_TRACE
 def event(stage,goal):
  if tr is not None:
   tr.append('safe_approach/physics_row',tr.n);tr.append('safe_approach/stage',stage);tr.append('safe_approach/goal',goal)
 event(0,retreat)
 if np.linalg.norm(retreat-runner.palm_pose()[0])>.002:
  runner.move_tag='contact_retreat_before_raise';runner.goto(retreat,rot,rounds=2,rate=.004,settle=.2)
 event(1,rise);runner.move_tag='contact_raise_before_final_approach'
 stable=[0]
 def measured_clear():
  low,_=hand_bounds(runner.model,runner.data)
  stable[0]=stable[0]+1 if low[2]>=top+.035 else 0
  return stable[0]*runner.model.opt.timestep>=.10
 runner.goto(rise,rot,rounds=2,rate=.004,settle=.3,on_step=measured_clear)
 runner.run(.2)
 lo,hi=hand_bounds(runner.model,runner.data);event(2,lo)
 if lo[2]<top+.025:raise RuntimeError('measured_hand_not_clear_before_final_approach')
 return {'hand_min_z':float(lo[2]),'table_top_z':top,'minimum_vertical_clearance_m':float(lo[2]-top)}

def install(pipeline,config):
 original=pipeline.base.walk_to_pose
 def walk(runner,goal_xy,goal_yaw,*args,**kwargs):
  if not getattr(runner,'_contact_first_approach_done',False):
   runner._contact_first_approach_done=True
   heading=np.array([np.cos(goal_yaw),np.sin(goal_yaw)])
   stage=np.asarray(goal_xy)-float(config.get('approach_staging_distance_m',.20))*heading
   original(runner,stage,goal_yaw,*args,**kwargs)
   raise_clear(runner)
  return original(runner,goal_xy,goal_yaw,*args,**kwargs)
 pipeline.base.walk_to_pose=walk
 return {'first_approach_staging_distance_m':float(config.get('approach_staging_distance_m',.20)),
         'measured_hand_vertical_clearance_before_final_walk_m':.025,'geometry_support':'axis-aligned tabletop approached from near-x edge','runtime_state_writes':False}
