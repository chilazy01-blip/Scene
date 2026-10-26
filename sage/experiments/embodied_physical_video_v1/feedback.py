"""World-frame coordinated arm targets and live box contact constraints."""
import numpy as np,mujoco
from .geometry import Arms,yaw,wrap
from .contact_projection import project
class Feedback:
    def __init__(self,m,c,robot,s,ref):
        self.m=m;self.c=c;self.s=s;self.ref=ref;self.arms=Arms(m,c);self.query=mujoco.MjData(m)
        self.qmap=np.array(c['qpos_by_pin']);self.upper=np.array(robot.get_joint_group_indices('upper_body'))
        self.ar=np.array(c['inspection']['groups']['left_arm']+c['inspection']['groups']['right_arm'])
        self.hands=np.array(c['inspection']['groups']['left_hand']+c['inspection']['groups']['right_hand'])
        self.ids=np.r_[self.ar,self.hands];self.last=None
    def target(self,d,phase):
        lo=int(min(phase,self.s['count']));hi=min(lo+1,self.s['count']);mix=phase-lo
        def interp(x):return x[min(lo,len(x)-1)]*(1-mix)+x[min(hi,len(x)-1)]*mix
        gl=self.s['goals'][min(lo,self.s['count']-1)];gh=self.s['goals'][min(hi,self.s['count']-1)]
        goal={k:np.array(v*(1-mix)+gh[k]*mix,copy=True) for k,v in gl.items()}
        goal['target_upper_body_pose']+=interp(self.ref['delta'])[self.qmap[self.upper]]
        planned=interp(self.ref['qpos']).copy()
        intended=planned[self.qmap].copy();intended[self.upper]=goal['target_upper_body_pose']
        planned[self.qmap[self.ids]]=intended[self.ids]
        poses=self.arms.poses(planned)
        initial=d.qpos.copy()
        initial[self.qmap[self.ids]]=intended[self.ids] if self.last is None else self.last[self.ids]
        initial[self.qmap[self.hands]]=intended[self.hands]
        q,ik=self.arms.solve(initial,poses,iterations=16)
        q[self.qmap[self.hands]]=intended[self.hands]
        q,hist=project(self.m,self.query,q,self.c,self.ids,depth=.005,iterations=20)
        target=intended.copy();target[self.ids]=q[self.qmap[self.ids]]
        if self.last is None:self.last=d.qpos[self.qmap].copy()
        diff=target-self.last
        factor=min(1.,.06/max(float(abs(diff[self.ar]).max()),1e-12),.24/max(float(abs(diff[self.hands]).max()),1e-12))
        target[self.ids]=self.last[self.ids]+factor*diff[self.ids]
        self.last=target.copy()
        goal['target_upper_body_pose']=target[self.upper].copy()
        # Waist intent stays from the source; waist execution remains native WBC.
        return goal,interp(self.ref['qpos']),factor,dict(ik=ik,projection_iterations=len(hist),shared_fraction=factor,max_target_arm_delta=float(abs(factor*diff[self.ar]).max()))
