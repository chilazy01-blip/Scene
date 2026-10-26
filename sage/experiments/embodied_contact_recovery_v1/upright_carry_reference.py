"""Measured object-orientation replanning through the retained arm motors."""
import numpy as np
from .object_pose_receding import segment_clear

class UprightCarryReference:
 def __init__(self,runner):
  self.rotation=runner.data.xmat[runner.cyl_bid].reshape(3,3).copy()
  self.target=runner.q_cmd.copy();self.last=None;self.replans=0
 def update(self,runner,row):
  m,d,ik=runner.model,runner.data,runner.ik
  if row%8==0 and row>0:
   palm,wrist=runner.palm_pose();relative=wrist.T@d.xmat[runner.cyl_bid].reshape(3,3)
   arm,resid,rr=ik.solve(d,palm,self.rotation@relative.T,iters=60)
   candidate=runner.q_cmd+np.clip(arm-runner.q_cmd,-.0036,.0036)
   check=segment_clear(runner,candidate,samples=5)
   self.last={'row':row,'ik_position_residual_m':resid,'ik_rotation_residual_deg':rr,'segment':check,'desired_joint_delta_rad':(arm-runner.q_cmd).tolist()}
   if resid>.003 or rr>1. or not check['passed']:return False
   self.target=candidate;self.replans+=1
  runner.q_cmd+=np.clip(self.target-runner.q_cmd,-.18*m.opt.timestep,.18*m.opt.timestep)
  return True
