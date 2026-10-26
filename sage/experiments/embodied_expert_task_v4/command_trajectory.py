"""Persistent joint-position commands with velocity, acceleration and range bounds."""
import numpy as np

class CommandTrajectory:
    def __init__(self,initial,indices,lower,upper,velocity_limits,acceleration_limits,dt):
        self.indices=np.asarray(indices,dtype=int);self.lower=np.asarray(lower)[self.indices];self.upper=np.asarray(upper)[self.indices];self.q=np.asarray(initial,dtype=float)[self.indices].copy();self.v=np.zeros(len(self.indices));self.vmax=np.asarray(velocity_limits,dtype=float);self.amax=np.asarray(acceleration_limits,dtype=float);self.dt=float(dt)
        if np.any(self.q<self.lower-1e-10) or np.any(self.q>self.upper+1e-10):raise ValueError('initial_command_outside_native_range')
        self.q=np.clip(self.q,self.lower,self.upper)
    def step(self,requested):
        target=np.clip(np.asarray(requested)[self.indices],self.lower,self.upper);delta=target-self.q;adt=self.amax*self.dt
        desired=np.sign(delta)*(np.sqrt(adt*adt+2*self.amax*np.abs(delta))-adt)
        position_lo=adt-np.sqrt(adt*adt+2*self.amax*np.maximum(self.q-self.lower,0.))
        position_hi=-adt+np.sqrt(adt*adt+2*self.amax*np.maximum(self.upper-self.q,0.))
        lo=np.maximum.reduce([-self.vmax,self.v-adt,position_lo]);hi=np.minimum.reduce([self.vmax,self.v+adt,position_hi])
        if np.any(lo>hi+1e-9):raise RuntimeError('command_trajectory_has_no_bounded_continuation')
        velocity=np.minimum(np.maximum(desired,lo),hi);q=self.q+self.dt*velocity;acceleration=(velocity-self.v)/self.dt
        if np.any(q<self.lower-1e-9) or np.any(q>self.upper+1e-9) or np.any(np.abs(velocity)>self.vmax+1e-9) or np.any(np.abs(acceleration)>self.amax+1e-7):raise RuntimeError('command_trajectory_bound_violation')
        result=np.asarray(requested).copy();result[self.indices]=q;self.q=q;self.v=velocity
        return result,dict(velocity=velocity.copy(),acceleration=acceleration.copy(),requested=target.copy(),applied=q.copy())
