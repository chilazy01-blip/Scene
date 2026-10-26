"""Collision-checkable joint-space return to the demonstrated initial empty-hand posture."""
import numpy as np
from .withdrawal import Withdraw
from .geometry import smooth
class Recover:
    def __init__(self,m,c,robot,d,command,neutral_goal):
        self.withdraw=Withdraw(m,c,robot,d,command)
        self.upper=self.withdraw.upper;self.arms=self.withdraw.ids
        self.hands=np.array(c['inspection']['groups']['left_hand']+c['inspection']['groups']['right_hand'])
        self.last=command.copy();self.start_time=float(d.time);self.start=None;self.clock=0.
        self.end=command.copy();self.end[self.upper]=neutral_goal['target_upper_body_pose']
        self.end[self.hands]=command[self.hands]
        self.height0=None;self.height1=np.asarray(neutral_goal['base_height_command']).copy()
    def target(self,d,current_height):
        elapsed=d.time-self.start_time
        if elapsed<.6:
            upper,meta=self.withdraw.target(d);self.last[self.upper]=upper
            return upper,np.asarray(current_height).copy(),dict(stage='clear_fingers',**meta)
        if self.start is None:
            self.start=self.last.copy();self.height0=np.asarray(current_height).copy()
        proposed=min(1.,self.clock+.02);desired=self.start+(self.end-self.start)*smooth(proposed)
        delta=desired-self.last;fraction=min(1.,.04/max(float(abs(delta[self.arms]).max()),1e-12))
        self.clock=min(1.,self.clock+.02*fraction);blend=smooth(self.clock)
        command=self.start+(self.end-self.start)*blend
        assert float(abs(command[self.arms]-self.last[self.arms]).max())<=.0401
        self.last=command
        height=self.height0*(1-blend)+self.height1*blend
        return command[self.upper].copy(),height,dict(stage='joint_return',shared_clock=self.clock,blend=float(blend),shared_fraction=fraction,ik_used=False,neutral_height=np.asarray(height).tolist())

