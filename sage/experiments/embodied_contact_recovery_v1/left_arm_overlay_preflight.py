"""Exercise actual versioned overlay timing and command isolation without physics."""
import sys
from types import SimpleNamespace
import numpy as np
from .work import E,R,c,finish
from . import compact_approach_control as previous
from . import compact_approach_control_r2 as candidate

def exercise(module,extra):
 names=c.read(R/'branches/A/source/model_config.json')['joint_names'];records=[]
 class Controller:
  joint_names=names
  def arm_overlay(self,target,proj_gravity=None):return target.copy()
 sys.modules['run']=SimpleNamespace(G1Controller=Controller)
 sys.modules['instrument']=SimpleNamespace(ACTIVE_TRACE=SimpleNamespace(n=0,append=lambda *a:None))
 ctrl=Controller();data=SimpleNamespace(time=0.,geom_xpos=np.array([[.351,0,.713]]));model=SimpleNamespace(geom=lambda name:SimpleNamespace(id=0),geom_size=np.array([[.4,.25,.02]]))
 def ramp(*args,**kwargs):
  for time in np.linspace(0.,2.5,11):
   data.time=time;kwargs['on_step']();records.append(ctrl.arm_overlay(np.arange(len(names),dtype=float)).tolist())
 runner=SimpleNamespace(ctrl=ctrl,data=data,model=model,ramp_to=ramp)
 p=SimpleNamespace(base=SimpleNamespace(walk_to_pose=lambda *a,**kw:(0.,0.)),EpisodeAborted=RuntimeError)
 saved=module.hand_bounds;module.hand_bounds=lambda *args:(np.array([0,0,1.]),np.array([0,0,1.1]))
 cfg={'compact_approach_plan':str(E/'D_COMPACT_APPROACH_POSE.json'),'left_arm_extra_offset_rad':extra}
 try:module.install(p,cfg);p.base.walk_to_pose(runner,[0.,0.],0.)
 finally:module.hand_bounds=saved
 return np.array(records),names

old,names=exercise(previous,{})
unchanged,_=exercise(candidate,{})
assert np.array_equal(old,unchanged)
changed,_=exercise(candidate,{'left_elbow_joint':-.10})
delta=changed-old;index=names.index('left_elbow_joint');others=[i for i in range(len(names)) if i!=index]
assert np.max(abs(delta[:,others]))==0.
assert np.max(abs(delta[:,index]+.10*np.minimum(np.linspace(0,2.5,11)/2.,1)))<1e-12
report={'passed':True,'physics_steps':0,'policy_calls':0,'zero_extra_offsets_exact_previous_commands':True,'only_declared_left_joint_changed':True,'additional_left_elbow_offset_rad':-.10,'maximum_command_difference_rad':float(np.max(abs(delta))),'same2s_causal_transition':True,'no_plant_changes':True,'not_dynamic_admission':True,'closed_D_method_reopened':False}
c.write(E/'D_LEFT_ARM_OVERLAY_PREFLIGHT.json',report);finish(report)
