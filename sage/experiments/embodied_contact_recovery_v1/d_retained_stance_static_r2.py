"""Read-only whole-body translated-route and preserved-tilt placement check."""
import os,sys
from pathlib import Path
import numpy as np
import h5py,mujoco
from .work import E,R,c,finish


def main(config_file):
 work=Path(os.environ['CONTINUOUS_JOB_DIR']);cfg=c.read(config_file)
 os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
 from .target_adapter_r4 import install
 install('A','gain_translation',work/'static_interface')
 import run
 from ik import pipeline as p,sim
 from .tripod_task_control_r6 import loaded_forbidden
 from .object_pose_receding import segment_clear
 from .pose_planner_static_r5 import solve
 from .velocity_transition import VelocityTransition
 folder=E/'jobs/D_tripod_window_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
 with h5py.File(folder/'TRACE.h5','r') as f:mujoco.mj_setState(m,d,f['substep/integration_after'][-1],mujoco.mjtState.mjSTATE_INTEGRATION)
 mujoco.mj_step=lambda *a,**kw: (_ for _ in ()).throw(AssertionError('no_integration'))
 mujoco.mj_forward(m,d);ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=sim.ArmIK6(m,ctrl)
 class Runner:
  model,data,cyl_bid=m,d,m.body('red_block').id
  def __init__(self):self.ik=ik
  def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
  def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
 runner=Runner();geo=p.scene_geometry(m);initial=d.qpos.copy();base=initial[:2].copy();obj=runner.cyl_pos().copy();oa=int(m.jnt_qposadr[m.joint('red_block_joint').id]);westblue=geo['blue_center'][0]-geo['blue_half'][0];westbrown=geo['brown_center'][0]-geo['brown_half'][0]
 objgoal=np.array([westblue+.08,geo['blue_center'][1]]);goal=objgoal-(obj[:2]-base);goal[0]=min(goal[0],westblue-.36);west=min(westbrown-.36,westblue-.36,goal[0]);points=[base,np.array([west,base[1]]),np.array([west,goal[1]]),goal];bad=[];samples=0
 for a,b in zip(points[:-1],points[1:]):
  for t in np.linspace(0.,1.,81):
   shift=a+t*(b-a)-base;d.qpos[:]=initial;d.qpos[:2]+=shift;d.qpos[oa:oa+2]+=shift;d.qvel[:]=0.;mujoco.mj_forward(m,d);samples+=1
   contact=loaded_forbidden(m,d)
   if contact:bad.append({'sample':samples,'geoms':contact})
 target_xyz=runner.cyl_pos().copy();target_xyz[:2]=objgoal
 result=solve(runner,geo,objgoal,target_xyz=target_xyz);path=segment_clear(runner,np.asarray(result['variables'][:-2]),samples=81)
 # Verify causal startup, commanded stopping and sign reversal retain bounded acceleration.
 transition=VelocityTransition(cfg['transport_velocity_cap'],cfg['transport_acceleration_cap']);prev=np.zeros(3);max_delta=np.zeros(3)
 for requested in [[-.4,.2,.3]]*70+[[0.,0.,0.]]*70+[[.4,-.2,-.3]]*70:
  issued=transition.command(requested);max_delta=np.maximum(max_delta,abs(issued-prev));assert np.all(abs(issued)<=np.array(cfg['transport_velocity_cap'])+1e-12);assert np.all(abs(issued-prev)<=np.array(cfg['transport_acceleration_cap'])*.02+1e-12);prev=issued
 report={'physics_steps':0,'policy_calls':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'body_goal_xy':goal.tolist(),'object_goal_xy':objgoal.tolist(),'waypoints':[x.tolist() for x in points],'base_target_west_clearance_m':float(westblue-goal[0]),'translation_static_samples':samples,'forbidden':bad,'placement_plan':result,'placement_path':path,'velocity_transition_max_delta':max_delta.tolist(),'passed':bool(not bad and goal[0]<=westblue-.36 and result['valid'] and path['passed']),'dynamic_route_qualified':False,'production_accepted':False}
 c.write(E/'D_RETAINED_ARM_STANCE_STATIC_R2.json',report);finish(report)

if __name__=='__main__':main(sys.argv[1])
