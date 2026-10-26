"""Actual D2 capture telemetry and measured missing-digit closure feasibility."""
import os,sys
from pathlib import Path
import numpy as np,h5py,mujoco
from .work import E,R,c,finish

def main():
 work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work));sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
 from .target_adapter_r4 import install
 install('A','gain_translation',work/'static_interface')
 import run
 from ik import sim
 from .planned_tripod_r2 import PlannedFingerServo,contact_geometry
 from .tripod_recontact import plan_recontact
 folder=E/'jobs/D_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m);measured=c.read(folder.parent/'D_MEASURED_TRIPOD_PLAN.json')
 with h5py.File(folder/'TRACE.h5','r') as f:
  observations=f['tripod/observation'][:];indices=f['finger_governor/physics_row'][:];history=f['finger_governor/control'][:];last=len(f['substep/qpos'])-1
  mujoco.mj_setState(m,d,f['substep/integration_after'][last],mujoco.mjtState.mjSTATE_INTEGRATION)
  mujoco.mj_forward(m,d);servo=PlannedFingerServo(m);ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=sim.ArmIK6(m,ctrl)
  class Runner:
   model,data,cyl_bid=m,d,m.body('red_block').id
   def __init__(self):self.ik=ik
   def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
   def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
  runner=Runner();geometry=contact_geometry(m,d,runner.cyl_bid);plan=plan_recontact(m,d,runner.cyl_bid);digits={}
  for digit in ['thumb','index','middle']:
   ids=[i for i,name in enumerate(servo.digits) if name==digit];latched=[]
   for i in ids:
    k=np.flatnonzero(history[:,i,1]==2)
    latched.append({'actuator':m.actuator(int(servo.aids[i])).name,'first_latched_source_row':int(indices[k[0]]) if len(k) else None,'final_telemetry':history[-1,i].tolist(),'final_actual_rad':float(d.qpos[servo.qa[i]]),'final_requested_rad':float(d.ctrl[servo.aids[i]])})
   digits[digit]=latched
  report={'physics_steps':0,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'capture_observations':observations.tolist(),'final_geometry':geometry,'digit_telemetry':digits,'arm_final_target_error_rad':(d.qpos[ik.qpos_idx]-np.array(measured['arm_target_rad'])).tolist(),'measured_missing_digit_replan':plan,'production_accepted':False}
 c.write(E/'D2_CAPTURE_CONTACT_ANALYSIS.json',report);finish(report)

if __name__=='__main__':main()
