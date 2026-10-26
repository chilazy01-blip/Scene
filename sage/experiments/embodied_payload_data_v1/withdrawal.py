"""Release clearance reference: retreat actual commanded palms in world frame."""
import numpy as np
from .geometry import Arms,smooth
class Withdraw:
    def __init__(self,m,c,robot,d,command):
        self.arms=Arms(m,c);self.qmap=np.array(c['qpos_by_pin'])
        self.ids=np.array(c['inspection']['groups']['left_arm']+c['inspection']['groups']['right_arm'])
        self.upper=np.array(robot.get_joint_group_indices('upper_body'))
        planned=d.qpos.copy()
        self.poses=self.arms.poses(planned);self.starts={}
        self.direction={}
        self.start_time=float(d.time);self.last=command.copy()
        for side,(pos,rot) in self.poses.items():
            outward=pos-d.qpos[50:53];outward[2]=0.;outward/=max(np.linalg.norm(outward),1e-12)
            self.direction[side]=outward
    def target(self,d):
        blend=smooth((d.time-self.start_time)/.8)
        poses={side:(pos+self.direction[side]*(.03*blend),rot) for side,(pos,rot) in self.poses.items()}
        seed=d.qpos.copy();seed[self.qmap[self.ids]]=self.last[self.ids]
        q,errors=self.arms.solve(seed,poses,iterations=20)
        delta=q[self.qmap[self.ids]]-self.last[self.ids]
        fraction=min(1.,.04/max(float(abs(delta).max()),1e-12))
        self.last[self.ids]+=fraction*delta
        return self.last[self.upper].copy(),dict(withdraw_blend=float(blend),ik=errors,shared_fraction=fraction,retreat_m=.03*blend)
