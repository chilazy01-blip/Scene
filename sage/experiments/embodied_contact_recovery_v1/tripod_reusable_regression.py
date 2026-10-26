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
r=Runner();candidates=c.read(E/'D_PREGRASP_ROLL_TRIPOD_ENDPOINT_AND_PATH.json')['candidates'];rows=[]
for original in [x for x in candidates if x['static_candidate'] and x['coordinated_straight_path']['passed']]:
 result=plan(r,original)
 assert max(abs(np.array(result['arm_target_rad'])-original['arm_target_rad']))<1e-12
 assert max(abs(np.array(result['finger_target_rad'])-original['finger_target_rad']))<1e-12
 rows.append({'roll_deg':original['palm_roll_change_deg'],'offset_m':original['palm_local_offset_m'],'result':result})
servo=PlannedFingerServo(m);q_before=d.qpos.copy();desired=np.array(rows[0]['result']['initial_finger_rad']);telemetry=servo.apply(m,d,desired)
assert np.array_equal(q_before,d.qpos) and np.all(d.ctrl>=m.actuator_ctrlrange[:,0]) and np.all(d.ctrl<=m.actuator_ctrlrange[:,1])
report={'physics_steps':0,'policy_calls':0,'cases':rows,'same_endpoints_as_frozen_static_search':True,
        'whole_robot_path_pass_count':sum(x['result']['valid'] for x in rows),'initial_reference_servo_commands_finite':bool(np.isfinite(telemetry).all()),
        'qualification':'All robot contact pairs now checked, extending the earlier hand-only acquisition path screen. Static only.',
        'dynamic_admission':False,'production_accepted':False}
c.write(E/'D_TRIPOD_REUSABLE_PLANNER_REGRESSION.json',report);finish(report)
