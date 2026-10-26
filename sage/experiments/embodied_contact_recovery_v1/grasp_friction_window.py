"""One authorized saved-state acquisition/support window, at most ten seconds."""
import os,sys,traceback
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from . import trace_r4
from .leg_interpolation import LegInterpolation
from .contact_finger_governor import ContactFingerGovernor
class WindowComplete(BaseException):pass

def main(case_file):
 cfg=c.read(case_file);work=Path(os.environ['CONTINUOUS_JOB_DIR']);folder=Path(cfg['source_folder']);start=int(cfg['start_row']);steps=int(cfg['saved_steps'])
 os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'));sys.modules['instrument']=trace_r4
 c.write(work/'USAGE.json',{k:0 for k in c.read(work/'REQUEST.json')['reservation']});tr=trace_r4.Trace(work/'episode','diagnostic');tr.install();error=None;completed=False;capture=False;lift_started=False
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
   policy=f['policy/walker_onnx'];idx=int(np.searchsorted(policy['physics_row'][:],start));last=policy['input'][next(iter(policy['input']))][idx].reshape(-1)[-32:-3]
  mujoco.mj_forward(m,d)
  source=R/'branches/A/source';policies=[run.ONNXPolicy(str(source/(n+'.onnx'))) for n in ['walker','croucher','rotator']]
  ctrl=run.G1Controller(m,d,*policies,c.read(source/'model_config.json'));ctrl.last_action=last.copy();ctrl.lin_vel_x=ctrl.lin_vel_y=ctrl.ang_vel_z=0.
  ids=[i for i,n in enumerate(ctrl.joint_names) if any(s in n for s in ['hip','knee','ankle'])];ctrl._contact_leg_interpolation=LegInterpolation(ids,8);ctrl._contact_leg_interpolation.apply(previous)
  sim.OUT_DIR=work/'episode/native_output';sim.OUT_DIR.mkdir(exist_ok=True);common_install(cfg)
  ik=sim.ArmIK6(m,ctrl);runner=p.HybridRunner(m,d,ctrl,ik,video=None,snapshots=False,sim_limit=300.,wall_limit=150.)
  runner.q_cmd=requested[ctrl.right_arm_indices].copy();runner.grip_alpha=runner.grip_alpha_f=.25;runner.grip_cap=None
  governor=ContactFingerGovernor(m,free_speed=.20,contact_preload=.03)
  c.write(work/'SAVED_INTERFACE_STATE.json',{'source_row':start,'initial_time':float(d.time),'last_action':last.tolist(),'initial_state_sha256':__import__('hashlib').sha256(initial.tobytes()).hexdigest(),'grip_request_start':.25,'source_hold_cap_replaced_by_measured_contact_governor':True})
  assert start%8==0 and steps<=4000
  old=mujoco.mj_step
  def bounded(model,data,*a,**kw):
   if tr.n>=steps:raise WindowComplete()
   telemetry=governor.apply(model,data);tr.append('finger_governor/control',telemetry)
   return old(model,data,*a,**kw)
  mujoco.mj_step=bounded
  rest=float(d.xpos[governor.obj,2]);stable=0
  while tr.n<min(2400,steps):
   alpha=min(1.,.25+.75*tr.n/1600);runner.grip_alpha=runner.grip_alpha_f=alpha;runner.step_once()
   opposed='thumb' in governor.latched and bool(governor.latched&{'index','middle'})
   stable=stable+1 if opposed and runner.finger_contacts()>=2 and runner.cyl_tilt_deg()<10. else 0
   if stable>=80:capture=True;break
  if capture:
   lift_started=True;palm,rot=runner.palm_pose();runner.move_tag='bounded_capture_lift'
   runner.goto(palm+np.array([0.,0.,.08]),rot,rounds=2,rate=.004,settle=.2)
  while tr.n<steps:runner.step_once()
  completed=True
 except WindowComplete:completed=True
 except BaseException:error=traceback.format_exc();print(error,flush=True)
 finally:summary=tr.close()
 report={'outcome':'engineering_failure' if error else 'success','window_completed':completed,'capture_gate_seen':capture,'lift_started':lift_started,'final_object_lift_m':float(d.xpos[governor.obj,2]-rest) if 'rest' in locals() else None,'contact_digits':sorted(governor.latched) if 'governor' in locals() else [],'summary':summary,'engineering_error':error,'new_complete_task_attempts':0,'full_task':False,'production_accepted':False}
 c.write(work/'DIAGNOSTIC.json',report);finish(report,tr.usage)
if __name__=='__main__':main(sys.argv[1])
