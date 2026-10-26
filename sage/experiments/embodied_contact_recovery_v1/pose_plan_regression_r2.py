"""Inspect D optimizer feasibility on saved pre-place states without advancing time."""
import os,sys
from pathlib import Path
import numpy as np
import h5py
import mujoco
from .work import E,R,finish,c
from .pose_planner_static_r2 import solve
work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ['NP_ROOT']=str(R);os.environ['NP_JOB']=str(work)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r4 import install
install('A','gain_translation',work/'static_interface')
import run
from ik.sim import ArmIK6
source=E/'jobs/grasp_friction_01/episode';m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl)
class Runner:
 model=m;data=d;cyl_bid=m.body('red_block').id
 def __init__(self):self.ik=ik
 def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
 def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
r=Runner();geo={'blue_top_z':.633,'blue_center':[-.3,-.8,.613],'blue_half':[.35,.25,.02]};rows=[]
with h5py.File(source/'TRACE.h5','r') as f:
 for sec in [47.5,47.99]:
  k=int(round((sec-38.)/.0025))-1;mujoco.mj_setState(m,d,f['substep/integration_before'][k],mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
  q=d.qpos.copy();v=d.qvel.copy();target=r.cyl_pos()[:2].copy();result=solve(r,geo,target)
  assert np.array_equal(q,d.qpos) and np.array_equal(v,d.qvel)
  rows.append({'source_time':sec,'source_row':k,'result':result})
report={'physics_steps':0,'policy_calls':0,'method':'D_object_pose_planning','decision_variables':'7arm joints plus2 stance offsets','physical_admission':False,'saved_pre_place_cases':rows,
        'scope':'Offline static optimizer regression; new low-preload grip state; local orientation planning only, not a transport plan; no dynamic success claimed'}
c.write(E/'D_LOW_PRELOAD_UPRIGHT_STATIC_REGRESSION.json',report);finish(report)
