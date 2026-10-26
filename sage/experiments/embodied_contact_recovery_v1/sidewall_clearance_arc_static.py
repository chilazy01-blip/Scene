"""Measured-state planner regression, including every robot collision pair."""
import os,sys
from pathlib import Path
import numpy as np
import mujoco
import h5py
from .work import E,R,c,finish
work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ.update(NP_ROOT=str(R),NP_JOB=str(work))
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from .target_adapter_r4 import install
install('A','gain_translation',work/'static_interface')
import run
from ik.sim import ArmIK6
from .planned_tripod import plan,PlannedFingerServo
folder=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(folder/'TRACE.h5','r') as f:state=f['substep/integration_before'][15200]
mujoco.mj_setState(m,d,state,mujoco.mjtState.mjSTATE_INTEGRATION);mujoco.mj_forward(m,d)
ctrl=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'));ik=ArmIK6(m,ctrl)
class Runner:
 model=m;data=d;cyl_bid=m.body('red_block').id
 def __init__(self):self.ik=ik
 def palm_pose(self):return d.site_xpos[ik.site_id].copy(),d.site_xmat[ik.site_id].reshape(3,3).copy()
 def cyl_pos(self):return d.xpos[self.cyl_bid].copy()
r=Runner()
from .tripod_clearance_arc import plan_arc
selected=c.read(E/'D_SIDEWALL_TRIPOD_SELECTED_PLAN.json')['selected'];grasp=plan(r,selected)
assert grasp['valid']
result=plan_arc(r,grasp)
report={'passed':result['valid'],'source_trace_sha256':c.sha(folder/'TRACE.h5'),'source_row':15200,'grasp':grasp,'clearance_arc':result,'new_physics_steps':0,'production_accepted':False}
c.write(E/'D_SIDEWALL_CLEARANCE_ARC_STATIC.json',report);finish(report)
