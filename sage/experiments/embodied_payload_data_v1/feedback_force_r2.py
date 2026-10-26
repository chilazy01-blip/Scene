"""Measured palm-contact admittance with common arm time scaling."""
import numpy as np,mujoco
from .geometry import Arms
class Feedback:
    def __init__(self,m,c,robot,s,ref):
        self.m=m;self.c=c;self.s=s;self.ref=ref;self.arms=Arms(m,c);self.sensed=mujoco.MjData(m)
        self.qmap=np.array(c['qpos_by_pin']);self.upper=np.array(robot.get_joint_group_indices('upper_body'))
        self.ids=np.array(c['inspection']['groups']['left_arm']+c['inspection']['groups']['right_arm'])
        self.offset={'left':0.,'right':0.};self.last=None
    def target(self,d,phase):
        lo=int(min(phase,self.s['count']));hi=min(lo+1,self.s['count']);mix=phase-lo
        def interp(x):return x[min(lo,len(x)-1)]*(1-mix)+x[min(hi,len(x)-1)]*mix
        gl=self.s['goals'][min(lo,self.s['count']-1)];gh=self.s['goals'][min(hi,self.s['count']-1)]
        goal={k:np.array(v*(1-mix)+gh[k]*mix,copy=True) for k,v in gl.items()}
        goal['target_upper_body_pose']+=interp(self.ref['delta'])[self.qmap[self.upper]]
        planned=interp(self.ref['qpos']).copy();intended=planned[self.qmap].copy()
        intended[self.upper]=goal['target_upper_body_pose'];planned[self.qmap[self.ids]]=intended[self.ids]
        poses=self.arms.poses(planned)
        sd=self.sensed;sd.qpos[:]=d.qpos;sd.qvel[:]=d.qvel;sd.ctrl[:]=d.ctrl;sd.qacc_warmstart[:]=d.qacc_warmstart;mujoco.mj_forward(self.m,sd)
        feedback={}
        for side in ['left','right']:
            gid=self.m.geom('gripper0_'+side+'_g0_col').id
            hits=[ct for ct in sd.contact if gid in [ct.geom1,ct.geom2] and (self.c['roles'][ct.geom1]=='object' or self.c['roles'][ct.geom2]=='object')]
            normal=sd.geom_xpos[gid]-sd.qpos[50:53];normal[2]=0.;normal/=max(np.linalg.norm(normal),1e-9)
            depth=0.
            if hits:
                ct=min(hits,key=lambda x:x.dist);depth=max(0.,-float(ct.dist));normal=ct.frame[:3]*(1 if ct.geom2==gid else -1)
            if phase<610 and hits:
                velocity=np.clip(4.*(depth-.004),-.002,.015)
                self.offset[side]=float(np.clip(self.offset[side]+.02*velocity,0.,.06))
            elif phase>=610:
                self.offset[side]*=.96
            pos,rot=poses[side];poses[side]=(pos+normal*self.offset[side],rot)
            feedback[side]=dict(actual_palm_depth=depth,outward_normal=normal.tolist(),admittance_offset=self.offset[side])
        initial=d.qpos.copy();initial[self.qmap[self.ids]]=intended[self.ids]
        q,ik=self.arms.solve(initial,poses,iterations=16)
        target=intended.copy();target[self.ids]=q[self.qmap[self.ids]]
        if self.last is None:self.last=d.qpos[self.qmap].copy()
        delta=target-self.last;factor=min(1.,.06/max(float(abs(delta[self.ids]).max()),1e-12))
        target[self.ids]=self.last[self.ids]+factor*delta[self.ids]
        self.last=target.copy();goal['target_upper_body_pose']=target[self.upper].copy()
        return goal,interp(self.ref['qpos']),factor,dict(ik=ik,palm_feedback=feedback,shared_fraction=factor,max_arm_command_delta=float(abs(factor*delta[self.ids]).max()))
