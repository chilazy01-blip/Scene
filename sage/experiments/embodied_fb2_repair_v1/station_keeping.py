"""Explicit world-position anchor around the native velocity-command policy.

Zero commanded velocity is not an absolute position anchor. This outer loop
uses measured root translation and velocity; the policy still supplies every
leg/waist command and MuJoCo still integrates every state.
"""
import numpy as np


class StationKeeper:
    def __init__(self,initial_qpos,dt=.02):
        self.anchor=np.asarray(initial_qpos[:2]).copy()
        self.heading=self.yaw(initial_qpos[3:7]);self.dt=dt;self.last=np.zeros(3)
        self.position_gain=2.;self.velocity_gain=.5;self.yaw_gain=1.;self.yaw_damping=.2
        self.max_xy=.25;self.max_yaw=.35;self.acceleration=np.array([.3,.3,.5])

    @staticmethod
    def yaw(q):
        w,x,y,z=np.asarray(q)
        return float(np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z)))

    def step(self,qpos,qvel):
        if not np.isfinite(qpos).all() or not np.isfinite(qvel).all():raise ValueError('nonfinite_root')
        theta=self.yaw(qpos[3:7]);c,s=np.cos(theta),np.sin(theta);R=np.array([[c,-s],[s,c]])
        error=self.anchor-qpos[:2]
        world=self.position_gain*error-self.velocity_gain*qvel[:2]
        requested=np.zeros(3);requested[:2]=R.T@world
        requested[2]=self.yaw_gain*np.arctan2(np.sin(self.heading-theta),np.cos(self.heading-theta))-self.yaw_damping*qvel[5]
        requested=np.clip(requested,[-self.max_xy,-self.max_xy,-self.max_yaw],[self.max_xy,self.max_xy,self.max_yaw])
        applied=self.last+np.clip(requested-self.last,-self.acceleration*self.dt,self.acceleration*self.dt)
        self.last=applied.copy()
        return applied,dict(anchor=self.anchor.copy(),position_error=error.copy(),measured_velocity=qvel[:2].copy(),requested=requested.copy(),applied=applied.copy(),world_velocity_request=world.copy(),physical_validation_required=True)
