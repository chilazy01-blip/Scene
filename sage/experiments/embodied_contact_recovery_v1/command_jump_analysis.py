"""Saved-state20ms target jump analysis; no integration or policy inference."""
import os,sys
from pathlib import Path
import h5py
import numpy as np
import mujoco
from .work import E,R,finish,c
from .leg_interpolation import LegInterpolation
work=Path(os.environ['CONTINUOUS_JOB_DIR']);os.environ['NP_ROOT']=str(R);os.environ['NP_JOB']=str(work)
sys.path.insert(0,str(R/'tools'));sys.path.insert(0,str(R/'branches/A/source'))
from target_adapter import install,CURRENT
install('A','gain_translation',work/'static_interface')
import run
source=R/'jobs/A_target_02/episode';m=mujoco.MjModel.from_binary_path(str(source/'MODEL.mjb'));d=mujoco.MjData(m)
controller=run.G1Controller(m,d,None,None,None,c.read(R/'branches/A/source/model_config.json'))
legids=[i for i,n in enumerate(controller.joint_names) if any(p in n for p in ['hip','knee','ankle'])]
assert len(legids)==12
native={n:i for i,n in enumerate(CURRENT['joint_names'])};remap=np.array([native[n] for n in controller.joint_names])
rows=[]
with h5py.File(source/'TRACE.h5','r') as f:
 for k in [5400,5504,5512,5520,5880]:
  current=f['substep/nominal_position_target'][k][remap];previous=f['substep/nominal_position_target'][k-1][remap]
  interp=LegInterpolation(legids);assert np.array_equal(interp.apply(previous),previous)
  first=interp.apply(current);series=[first]+[interp.apply(current) for _ in range(7)]
  assert np.allclose(series[-1],current,atol=1e-12)
  upper=np.setdiff1d(np.arange(len(current)),legids);assert all(np.array_equal(x[upper],current[upper]) for x in series)
  variants={}
  for label,target in [('instant',current),('first_interpolated',first)]:
   d.qpos[:]=f['substep/qpos'][k-1];d.qvel[:]=f['substep/qvel'][k-1];d.qacc_warmstart[:]=f['substep/qacc'][k-1];d.ctrl[:]=f['substep/ctrl'][k-1]
   controller.apply_pd_control(target);command=d.ctrl.copy();mujoco.mj_forward(m,d)
   feet=[]
   for side in ['left','right']:
    bid=m.body(side+'_ankle_roll_link').id;gs=[g for g in range(m.ngeom) if m.geom_bodyid[g]==bid and m.geom_type[g]==mujoco.mjtGeom.mjGEOM_SPHERE and m.geom_contype[g]]
    gid=min(gs,key=lambda g:d.geom_xpos[g,2]-m.geom_size[g,0]);point=d.geom_xpos[gid]
    j=np.zeros((3,m.nv));jd=np.zeros_like(j);mujoco.mj_jac(m,d,j,None,point,bid);mujoco.mj_jacDot(m,d,jd,None,point,bid)
    feet.append({'side':side,'height':float(point[2]-m.geom_size[gid,0]),'vz':float(j[2]@d.qvel),'az':float(j[2]@d.qacc+jd[2]@d.qvel)})
   variants[label]={'feet':feet,'control_difference_from_record':float(np.max(abs(command-f['substep/ctrl'][k]))),'ctrl':command.tolist()}
  rows.append({'row':k,'max_requested_leg_jump_rad':float(max(abs(current[legids]-previous[legids]))),'max_first_interpolated_jump_rad':float(max(abs(first[legids]-previous[legids]))),'variants':variants})
report={'physics_steps':0,'policy_calls':0,'interpolation_period_s':.02,'causal':True,'upper_and_hand_commands_unchanged':True,'rows':rows,'dynamic_effect':'unverified; needs approved bounded diagnostic','no_plant_parameter_change':True}
c.write(E/'COMMAND_JUMP_STATIC_ANALYSIS.json',report);finish(report)
