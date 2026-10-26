"""Saved-state correction feasibility and contract checks; zero integration."""
import numpy as np
import h5py
import mujoco
from .work import E,R,finish,c
from .landing_barrier import LandingBarrier
p=R/'jobs/A_target_02/episode';m=mujoco.MjModel.from_binary_path(str(p/'MODEL.mjb'));d=mujoco.MjData(m);guard=LandingBarrier(m)
checks=[]
with h5py.File(p/'TRACE.h5','r') as f:
 for k in [5400,5500,5510,5520,5529,5560,5680,5880]:
  d.qpos[:]=f['substep/qpos'][k-1];d.qvel[:]=f['substep/qvel'][k-1];d.qacc_warmstart[:]=f['substep/qacc'][k-1];d.ctrl[:]=f['substep/ctrl'][k];mujoco.mj_forward(m,d)
  q=d.qpos.copy();v=d.qvel.copy();ctrl=d.ctrl.copy();model=m.geom_solref.copy()
  result=guard.apply(d)
  assert np.array_equal(q,d.qpos) and np.array_equal(v,d.qvel) and np.array_equal(model,m.geom_solref)
  assert not np.any(d.qfrc_applied) and not np.any(d.xfrc_applied)
  assert np.max(abs(d.ctrl-ctrl))<=15.000001
  for a in guard.aids:assert m.actuator_ctrlrange[a,0]-1e-6<=d.ctrl[a]<=m.actuator_ctrlrange[a,1]+1e-6
  checks.append({'row':k,'correction':result})
assert guard.changed>=2 and guard.infeasible==0
report={'passed':True,'physics_steps':0,'contract':'Finite-state acceleration feasibility only; requires bounded dynamic contact validation','checks':checks,'guard':guard.report()}
c.write(E/'LANDING_BARRIER_STATIC_REGRESSION.json',report);finish(report)
