"""Prepared ten-second D planned acquisition/lift diagnostic, not a full task."""
import os,sys,traceback
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,R,c,finish
from . import trace_r4
from .leg_interpolation import LegInterpolation
from .planned_tripod_world_offset import plan,PlannedFingerServo,contact_geometry,forbidden_robot_contacts

class WindowComplete(BaseException): pass

def main(case_file):
 approval=c.read(E/'DIAGNOSTIC_WINDOW_REPLAN_APPROVAL.json')
 assert approval['approved'] and approval['proposal_sha256']==c.sha(E/'DIAGNOSTIC_WINDOW_REPLAN_PROPOSAL.json')
 cfg=c.read(case_file);work=Path(os.environ['CONTINUOUS_JOB_DIR']);folder=Path(cfg['source_folder']);start=int(cfg['start_row']);steps=int(cfg['saved_steps'])
 assert start%8==0 and 0<steps<=4000
 os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'));sys.modules['instrument']=trace_r4
 c.write(work/'USAGE.json',{key:0 for key in c.read(work/'REQUEST.json')['reservation']})
 tr=trace_r4.Trace(work/'episode','diagnostic');tr.install();error=None;abort=None;captured=False;lift_started=False;completed=False
 try:
  from .target_adapter_r4 import install as target_install
  target_install('A','gain_translation',work/'episode')
  import run
  from ik import pipeline as p,sim
  from .common_control import install as common_install
  m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
  with h5py.File(folder/'TRACE.h5','r') as f:
   initial=f['substep/integration_before'][start];mujoco.mj_setState(m,d,initial,mujoco.mjtState.mjSTATE_INTEGRATION)
   previous=f['interpolation/applied'][start-1];requested=f['interpolation/requested'][start-1]
   policy=f['policy/walker_onnx'];idx=int(np.searchsorted(policy['physics_row'][:],start));assert int(policy['physics_row'][idx])==start
   last=policy['input'][next(iter(policy['input']))][idx].reshape(-1)[-32:-3]
  mujoco.mj_forward(m,d)
  source=R/'branches/A/source';policies=[run.ONNXPolicy(str(source/(name+'.onnx'))) for name in ['walker','croucher','rotator']]
  ctrl=run.G1Controller(m,d,*policies,c.read(source/'model_config.json'));ctrl.last_action=last.copy();ctrl.lin_vel_x=ctrl.lin_vel_y=ctrl.ang_vel_z=0.
  ids=[i for i,name in enumerate(ctrl.joint_names) if any(x in name for x in ['hip','knee','ankle'])]
  ctrl._contact_leg_interpolation=LegInterpolation(ids,8);ctrl._contact_leg_interpolation.apply(previous);common_install(cfg)
  sim.OUT_DIR=work/'episode/native_output';sim.OUT_DIR.mkdir(exist_ok=True)
  ik=sim.ArmIK6(m,ctrl);runner=p.HybridRunner(m,d,ctrl,ik,video=None,snapshots=False,sim_limit=300.,wall_limit=210.)
  runner.q_cmd=requested[ctrl.right_arm_indices].copy();runner.grip_cap=None;runner.grip_alpha=runner.grip_alpha_f=1.
  selected=c.read(cfg['tripod_template'])['selected'];planned=plan(runner,selected);c.write(work/'MEASURED_TRIPOD_PLAN.json',planned)
  if not planned['valid']:raise p.EpisodeAborted('D_tripod_measured_plan_infeasible')
  from .tripod_clearance_arc_r2 import plan_arc
  arc=plan_arc(runner,planned);c.write(work/'MEASURED_CLEARANCE_ARC.json',arc)
  if not arc['valid']:raise p.EpisodeAborted('D_tripod_clearance_arc_infeasible')
  servo=PlannedFingerServo(m);desired=np.asarray(planned['initial_finger_rad']).copy();finger_start=desired.copy();finger_target=np.asarray(planned['finger_target_rad'])
  arm_start=runner.q_cmd.copy();arm_target=np.asarray(planned['arm_target_rad'])
  duration=max(float(np.max(abs(arm_target-arm_start)))/.18,float(np.max(abs(finger_target-finger_start)))/.18,.4)
  duration=max(duration,arc['required_duration_s'])
  if duration>5.8:raise p.EpisodeAborted('D_tripod_plan_exceeds_diagnostic_motion_time')
  time_start=float(d.time);object_start=runner.cyl_pos().copy();raw=mujoco.mj_step;desired_velocity=np.zeros_like(desired)
  def step(model,data,*args,**kwargs):
   if tr.n>=steps:raise WindowComplete()
   telemetry=servo.apply(model,data,desired,desired_velocity);tr.append('finger_reference_velocity',desired_velocity);tr.append('finger_governor/control',telemetry);tr.append('finger_governor/physics_row',tr.n)
   return raw(model,data,*args,**kwargs)
  mujoco.mj_step=step
  c.write(work/'SAVED_INTERFACE_STATE.json',{'source_row':start,'time':time_start,'last_action':last.tolist(),'initial_sha256':__import__('hashlib').sha256(initial.tobytes()).hexdigest(),'planned_motion_seconds':duration})
  stable=0
  while d.time-time_start<6.5:
   fraction=min(1.,(d.time-time_start+m.opt.timestep)/duration)
   runner.q_cmd=np.asarray([np.interp(fraction,arc['fractions'],np.asarray(arc['arm_path_rad'])[:,j]) for j in range(7)]);desired[:]=finger_start+fraction*(finger_target-finger_start)
   desired_velocity[:]=(finger_target-finger_start)/duration if fraction<1. else 0.
   runner.step_once();geometry=contact_geometry(m,d,runner.cyl_bid)
   if geometry['forbidden'] or forbidden_robot_contacts(m,d,runner.cyl_bid):raise p.EpisodeAborted('D_tripod_actual_forbidden_contact')
   if geometry['maximum_object_penetration_m']>.01:raise p.EpisodeAborted('D_tripod_actual_penetration_limit')
   good=geometry['digits']==['index','middle','thumb'] and geometry['rank']==6 and runner.cyl_tilt_deg()<10.
   stable=stable+1 if good and fraction==1. else 0
   if tr.n%80==0:tr.append('tripod/observation',[tr.n,fraction,geometry['contacts'],geometry['rank'],runner.cyl_tilt_deg()])
   if stable*m.opt.timestep>=.2:captured=True;break
  if not captured:raise p.EpisodeAborted('D_tripod_three_digit_capture_not_stable')
  desired_velocity[:]=0.
  lift_started=True;palm,wrist=runner.palm_pose();runner.move_tag='D_tripod_measured_lift'
  def monitor():
   geom=contact_geometry(m,d,runner.cyl_bid)
   if geom['rank']<6 or geom['digits']!=['index','middle','thumb']:raise p.EpisodeAborted('D_tripod_wrench_rank_lost_during_lift')
   if geom['forbidden'] or forbidden_robot_contacts(m,d,runner.cyl_bid):raise p.EpisodeAborted('D_tripod_forbidden_during_lift')
   return False
  runner.goto(palm+np.array([0.,0.,.08]),wrist,rounds=2,rate=.004,settle=0.,on_step=monitor)
  while tr.n<steps:runner.step_once();monitor()
  completed=True
 except WindowComplete:completed=True
 except BaseException as exc:
  if 'p' in locals() and isinstance(exc,p.EpisodeAborted):abort=str(exc);completed=True
  else:error=traceback.format_exc();print(error,flush=True)
 finally:summary=tr.close()
 report={'outcome':'engineering_failure' if error else 'success','window_completed':completed,'scientific_window_abort':abort,'capture_gate_seen':captured,'lift_started':lift_started,
         'final_lift_m':float(runner.cyl_pos()[2]-object_start[2]) if 'object_start' in locals() else None,
         'final_grasp_geometry':contact_geometry(m,d,runner.cyl_bid) if 'runner' in locals() else None,
         'summary':summary,'engineering_error':error,'new_complete_task_attempts':0,'full_task':False,'production_accepted':False}
 c.write(work/'DIAGNOSTIC.json',report);finish(report,tr.usage)

if __name__=='__main__':main(sys.argv[1])
