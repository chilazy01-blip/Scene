"""Saved pre-contact approach window: stop outside the table, raise, then hold."""
import os,sys,traceback
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish
from . import trace_r3
from .leg_interpolation import LegInterpolation
class WindowComplete(BaseException):pass

def main(case_file):
 cfg=c.read(case_file);work=Path(os.environ['CONTINUOUS_JOB_DIR']);folder=Path(cfg['source_folder']);start=int(cfg['start_row']);steps=int(cfg['saved_steps'])
 os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'));sys.modules['instrument']=trace_r3
 c.write(work/'USAGE.json',{k:0 for k in c.read(work/'REQUEST.json')['reservation']});tr=trace_r3.Trace(work/'episode','diagnostic');tr.install();error=None;completed=False;clearance=None
 try:
  from .target_adapter_r3 import install as target_install
  target_install('A','gain_translation',work/'episode')
  import run
  from ik import pipeline as p,sim
  from .common_control import install as common_install
  from .methods_r4 import install
  from .safe_approach_r2 import raise_clear
  m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
  with h5py.File(folder/'TRACE.h5','r') as f:
   mujoco.mj_setState(m,d,f['substep/integration_before'][start],mujoco.mjtState.mjSTATE_INTEGRATION)
   previous=f['interpolation/applied'][start-1];requested=f['interpolation/requested'][start-1]
   policy=f['policy/walker_onnx'];pr=policy['physics_row'][:];idx=int(np.searchsorted(pr,start));last=policy['input'][next(iter(policy['input']))][idx].reshape(-1)[-32:-3]
  mujoco.mj_forward(m,d)
  source=R/'branches/A/source';policies=[run.ONNXPolicy(str(source/(n+'.onnx'))) for n in ['walker','croucher','rotator']]
  ctrl=run.G1Controller(m,d,*policies,c.read(source/'model_config.json'));ctrl.last_action=last.copy();ctrl.lin_vel_x=ctrl.lin_vel_y=ctrl.ang_vel_z=0.
  ids=[i for i,n in enumerate(ctrl.joint_names) if any(s in n for s in ['hip','knee','ankle'])];ctrl._contact_leg_interpolation=LegInterpolation(ids,cfg.get('interpolation_substeps',8));ctrl._contact_leg_interpolation.apply(previous)
  sim.OUT_DIR=work/'episode/native_output';sim.OUT_DIR.mkdir(exist_ok=True)
  common_install(cfg);install(p,cfg)
  ik=sim.ArmIK6(m,ctrl);runner=p.HybridRunner(m,d,ctrl,ik,video=None,snapshots=False,sim_limit=300.,wall_limit=110.)
  runner.q_cmd=requested[ctrl.right_arm_indices].copy()
  ratios=[float(d.ctrl[a]/closed) for a,closed in ctrl.right_finger_actuators]
  runner.grip_alpha=float(np.median(ratios[:3]));runner.grip_alpha_f=float(np.median(ratios[3:]))
  c.write(work/'SAVED_INTERFACE_STATE.json',{'source_row':start,'initial_time':float(d.time),'grip_alpha':runner.grip_alpha,'grip_alpha_f':runner.grip_alpha_f,'last_action':last.tolist(),'source_command_replaced_by_stopping':True,'physics_state_restored_exactly':True})
  assert start%8==0 and steps<=4000
  old=mujoco.mj_step
  def bounded(model,data,*a,**kw):
   if tr.n>=steps:raise WindowComplete()
   return old(model,data,*a,**kw)
  mujoco.mj_step=bounded
  clearance=raise_clear(runner)
  while tr.n<steps:runner.step_once()
  completed=True
 except WindowComplete:completed=True
 except BaseException:error=traceback.format_exc();print(error,flush=True)
 finally:summary=tr.close()
 report={'outcome':'engineering_failure' if error else 'success','window_completed':completed,'clearance_result':clearance,'summary':summary,'engineering_error':error,'new_complete_task_attempts':0,'full_task':False,'production_accepted':False}
 c.write(work/'DIAGNOSTIC.json',report);finish(report,tr.usage)
if __name__=='__main__':main(sys.argv[1])
