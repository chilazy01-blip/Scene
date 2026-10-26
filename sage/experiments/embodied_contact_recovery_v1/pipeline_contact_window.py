"""Strictly bounded initial contact window through the actual common task interface."""
import os,sys,traceback
from pathlib import Path
import numpy as np,mujoco
from .work import E,R,c,finish
from . import trace_r3
class WindowComplete(BaseException):pass

def main(case_file):
 config=c.read(case_file);work=Path(os.environ['CONTINUOUS_JOB_DIR'])
 os.environ.update(NP_ROOT=str(R),NP_JOB=str(work),CONTACT_NAMED_INITIAL='1',CONTACT_STOW_JOINT=config['stow_joint'],CONTACT_STOW_OFFSET=str(config['stow_offset_rad']))
 sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'));sys.modules['instrument']=trace_r3
 c.write(work/'USAGE.json',{k:0 for k in c.read(work/'REQUEST.json')['reservation']})
 tr=trace_r3.Trace(work/'episode','diagnostic');tr.install();error=None;completed=False
 try:
  from .target_adapter_r3 import install as target_install
  target_install('A','gain_translation',work/'episode')
  from ik import pipeline as p,sim
  from .common_control import install as common_install
  from .methods_r4 import install
  sim.OUT_DIR=work/'episode/native_output';sim.OUT_DIR.mkdir(exist_ok=True);p.GRASP_DZ_MAX=.032
  c.write(work/'COMMON_CONTROL.json',common_install(config));c.write(work/'METHOD.json',install(p,config))
  steps=int(config['saved_steps']);assert steps<=4000
  old=mujoco.mj_step
  def bounded(m,d,*a,**kw):
   if tr.n>=steps:raise WindowComplete()
   if tr.n==0:
    expected=mujoco.MjData(m);mujoco.mj_setState(m,expected,np.load(config['prepared_initial_state'])['integration_state'],mujoco.mjtState.mjSTATE_INTEGRATION)
    expected.qpos[m.jnt_qposadr[m.joint(config['stow_joint']).id]]+=config['stow_offset_rad']
    delta=float(np.max(abs(d.qpos-expected.qpos)));velocity=float(np.max(abs(d.qvel-expected.qvel)))
    c.write(work/'INITIAL_STATE_CHECK.json',{'max_qpos_error':delta,'max_qvel_error':velocity,'source':config['prepared_initial_state'],'stow_offset_rad':config['stow_offset_rad'],'time':float(d.time)})
    assert delta<1e-10 and velocity<1e-10 and d.time==expected.time,'bound_initial_condition_mismatch'
   return old(m,d,*a,**kw)
  mujoco.mj_step=bounded
  result=p.run_once(**config['kwargs'],video=None,snapshots=False,sim_limit=300.,wall_limit=110.)
  error='Pipeline returned before bounded window ended: '+repr(result)
 except WindowComplete:completed=True
 except BaseException:error=traceback.format_exc();print(error,flush=True)
 finally:summary=tr.close()
 report={'outcome':'success' if completed and not error else 'engineering_failure','window_completed':completed,'summary':summary,'engineering_error':error,'new_complete_task_attempts':0,'full_task':False,'production_accepted':False,'scope':'Initial10s maximum saved-initial-state contact window, through retained pipeline and shared C/D interface repairs'}
 c.write(work/'DIAGNOSTIC.json',report);finish(report,tr.usage)
if __name__=='__main__':main(sys.argv[1])
