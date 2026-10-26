"""After support-confirmed release: separate fingertips, retract unloaded arms."""
import numpy as np
from .withdrawal import Withdraw as OriginalWithdraw
from .geometry import smooth,yaw
class Withdraw(OriginalWithdraw):
    def __init__(self,m,c,robot,d,command):
        super().__init__(m,c,robot,d,command)
        angle=yaw(d.qpos[3:7])
        self.backward=np.array([-np.cos(angle),-np.sin(angle),0.])
    def target(self,d):
        t=d.time-self.start_time
        outward=smooth(t/.45);back=smooth((t-.35)/.85);down=smooth((t-.80)/.50)
        poses={side:(pos+self.direction[side]*(.03*outward)+self.backward*(.15*back)+np.array([0.,0.,-.04])*down,rot) for side,(pos,rot) in self.poses.items()}
        seed=d.qpos.copy();seed[self.qmap[self.ids]]=self.last[self.ids]
        q,errors=self.arms.solve(seed,poses,iterations=20)
        delta=q[self.qmap[self.ids]]-self.last[self.ids]
        fraction=min(1.,.04/max(float(abs(delta).max()),1e-12))
        self.last[self.ids]+=fraction*delta
        return self.last[self.upper].copy(),dict(ik=errors,shared_fraction=fraction,outward_m=.03*outward,backward_m=.15*back,downward_m=.04*down,trajectory='Unloaded hand recovery only after support-confirmed release')

