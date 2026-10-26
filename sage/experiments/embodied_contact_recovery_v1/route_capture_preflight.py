"""Regression for duplicate docking removal and final opening control semantics."""
from types import SimpleNamespace
import numpy as np,h5py,mujoco
from .work import E,c,finish
from . import safe_approach_r2,safe_approach_r3
from .contact_finger_governor import ContactFingerGovernor as OldGovernor
from .contact_finger_governor_r2 import ContactFingerGovernor

def route(module):
 events=[];data=SimpleNamespace(qpos=np.array([-1.3243,.071,0.,1.,0.,0.,0.]))
 runner=SimpleNamespace(data=data)
 def hybrid(r,goal,yaw,*a,**kw):
  goal=np.asarray(goal);distance=np.linalg.norm(goal-r.data.qpos[:2])
  if distance<=.5:events.append(('unnecessary_dock',*(goal-np.array([.6,0.]))))
  events.append(('hybrid_goal',*goal));r.data.qpos[:2]=goal;return 0.,0.
 def direct(r,goal,**kw):events.append(('direct_goal',*goal));r.data.qpos[:2]=goal;return 0.
 p=SimpleNamespace(base=SimpleNamespace(walk_to_pose=hybrid,yaw_err_to=lambda d,y:0.),ep=SimpleNamespace(walk_to=direct))
 original=module.raise_clear;module.raise_clear=lambda r:events.append(('measured_raise',))
 try:module.install(p,{'approach_staging_distance_m':.2});p.base.walk_to_pose(runner,[-.30,.05],0.)
 finally:module.raise_clear=original
 return events
before=route(safe_approach_r2);after=route(safe_approach_r3)
assert any(x[0]=='unnecessary_dock' for x in before)
assert not any(x[0]=='unnecessary_dock' for x in after)
assert [x[0] for x in after]==['hybrid_goal','measured_raise','direct_goal']
folder=E/'jobs/grasp_friction_01/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
with h5py.File(folder/'TRACE.h5','r') as f:mujoco.mj_setState(m,d,f['substep/integration_before'][-1],mujoco.mjtState.mjSTATE_INTEGRATION)
mujoco.mj_forward(m,d);old=OldGovernor(m);new=ContactFingerGovernor(m)
for g in (old,new):g.latched.update(['thumb','middle','index'])
closed=np.array([.8,-.9,-1.5,1.4,1.5,1.4,1.5]);d.ctrl[old.aids]=closed;prior=old.apply(m,d);d.ctrl[new.aids]=closed;current=new.apply(m,d)
assert np.array_equal(prior,current),'closing_changes_validated_algorithm'
d.ctrl[new.aids]=0.;opened=new.apply(m,d)
assert all((x[5]-x[2])*x[2]<=0 for x in opened)
assert np.max(abs(opened[:,5]-opened[:,2]))<.09
report={'physics_steps':0,'policy_calls':0,'passed':True,'old_route':before,'repaired_route':after,
 'same_closing_commands_on_saved_held_state':True,'opening_toward_zero':True,
 'opening_preload_rad':(opened[:,5]-opened[:,2]).tolist(),
 'evidence_boundary':'Control-flow regression proves removal of duplicate0.60m retreat. Forward gait and contact acquisition retain previously tested primitives. No new dynamic or numerical pass is claimed.',
 'production_accepted':False}
c.write(E/'ROUTE_CAPTURE_PREFLIGHT.json',report);finish(report)
