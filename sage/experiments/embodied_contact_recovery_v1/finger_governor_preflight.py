"""Static regression of friction-aware commands and physical immutability guard."""
import numpy as np,h5py,mujoco
from .work import E,c,finish
from .plant_guard import PlantGuard
from .contact_finger_governor import ContactFingerGovernor
folder=E/'jobs/C_development_02/episode';m=mujoco.MjModel.from_binary_path(str(folder/'MODEL.mjb'));d=mujoco.MjData(m)
guard=PlantGuard(m);guard.check(m)
original=m.dof_damping[0];m.dof_damping[0]=original+.1;blocked=False
try:guard.check(m)
except AssertionError as ex:blocked='runtime_plant_mutation:dof_damping' in str(ex)
finally:m.dof_damping[0]=original
assert blocked;guard.check(m)
with h5py.File(folder/'TRACE.h5','r') as f:mujoco.mj_setState(m,d,f['substep/integration_before'][15200],mujoco.mjtState.mjSTATE_INTEGRATION)
mujoco.mj_forward(m,d);g=ContactFingerGovernor(m);before=d.qpos.copy();vel=d.qvel.copy();clock=d.time
closed=np.array([.8,-.9,-1.5,1.4,1.5,1.4,1.5]);d.ctrl[g.aids]=closed;free=g.apply(m,d)
assert np.max(abs(free[:,5]-free[:,2]))<.09
assert not g.latched
g.latched.update(g.digits);d.ctrl[g.aids]=closed;contact=g.apply(m,d)
assert np.max(abs(contact[:,5]-contact[:,2]))<=.0300000001
assert np.array_equal(before,d.qpos) and np.array_equal(vel,d.qvel) and clock==d.time
guard.check(m)
report={'physics_steps':0,'passed':True,'mutation_guard_regression':blocked,'free_preload_rad':(free[:,5]-free[:,2]).tolist(),'contact_preload_rad':(contact[:,5]-contact[:,2]).tolist(),'plant_sha256':guard.sha256,'physical_state_unchanged':True,'source_state':str(folder),'dynamic_qualification':False,'production_accepted':False}
c.write(E/'FINGER_GOVERNOR_PREFLIGHT.json',report);finish(report)
