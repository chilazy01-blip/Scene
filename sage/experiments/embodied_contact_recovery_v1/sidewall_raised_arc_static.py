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
from .planned_tripod_world_offset import plan,PlannedFingerServo
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
from .tripod_clearance_arc_r2 import plan_arc
from .grasp_force_certificate import certify
from .planned_tripod_r2 import FINGER_NAMES
fa=[m.jnt_qposadr[m.joint('right_hand_'+n+'_joint').id] for n in FINGER_NAMES]
rows=[];template=c.read(E/'D_SIDEWALL_TRIPOD_SELECTED_PLAN.json')['selected']
for height in [.005,.010,.015]:
    selected={**template,'palm_world_offset_m':[0.,0.,height]};grasp=plan(r,selected)
    row={'world_height_offset_m':height,'selected':selected,'grasp':grasp,'valid':False}
    if grasp.get('valid'):
        arc=plan_arc(r,grasp);scratch=mujoco.MjData(m);scratch.qpos[:]=d.qpos;scratch.qpos[ik.qpos_idx]=grasp['arm_target_rad'];scratch.qpos[fa]=grasp['finger_target_rad'];mujoco.mj_forward(m,scratch)
        certificate=certify(m,scratch,r.cyl_bid);side_only=bool(certificate['object_contact_geoms']) and set(certificate['object_contact_geoms'])=={'red_cylinder'}
        row.update(clearance_arc=arc,force_certificate=certificate,all_digits_on_sidewall=side_only,valid=arc['valid'] and side_only and certificate['linearized_force_closure'] and certificate['gravity_equilibrium_feasible'])
    rows.append(row)
valid=[x for x in rows if x['valid']]
report={'passed':bool(valid),'candidates':rows,'source_trace_sha256':c.sha(folder/'TRACE.h5'),'source_row':15200,'new_physics_steps':0,'production_accepted':False}
c.write(E/'D_SIDEWALL_RAISED_CLEARANCE_STATIC.json',report)
if valid:
    chosen=min(valid,key=lambda x:x['world_height_offset_m'])
    c.write(E/'D_SIDEWALL_RAISED_SELECTED_PLAN.json',{**chosen,'selection_rule':'Smallest of5/10/15mm upward world shift meeting6mm full arc hand-table clearance,all sidewall contacts,original speed/time limits and ideal force closure.','static_report_sha256':c.sha(E/'D_SIDEWALL_RAISED_CLEARANCE_STATIC.json'),'dynamic_admission':False,'production_accepted':False})
finish(report)
