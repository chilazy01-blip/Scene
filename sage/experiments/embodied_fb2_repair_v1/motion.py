"""Measured-velocity stopping with a persistent endpoint, followed by true hold.

The bounds describe a command trajectory, not a proof of physical braking.
Physical validation and the runtime distance/velocity guard remain mandatory.
"""
import numpy as np
from sage.experiments.embodied_expert_task_v4.command_trajectory_r2 import CommandTrajectory


class StopTrajectory:
    def __init__(self,q,velocity,acceleration,lower,upper):
        self.q=np.asarray(q,dtype=float).copy();self.v=np.asarray(velocity,dtype=float).copy()
        self.a=np.asarray(acceleration,dtype=float).copy()
        if self.q.shape!=self.v.shape or self.q.shape!=self.a.shape or np.any(self.a<=0):
            raise ValueError('invalid_stop_state')
        self.duration=np.abs(self.v)/self.a
        self.endpoint=self.q+self.v*np.abs(self.v)/(2*self.a)
        if np.any(self.endpoint<lower) or np.any(self.endpoint>upper):
            raise ValueError('no_bounded_stop_inside_joint_range')

    def sample(self,elapsed):
        t=np.minimum(max(0.,elapsed),self.duration)
        acceleration=-np.sign(self.v)*self.a
        q=self.q+self.v*t+.5*acceleration*t*t
        v=self.v+acceleration*t
        return q,v,np.where(t<self.duration,acceleration,0.)


class MotionGovernor:
    def __init__(self,initial,indices,lower,upper,vmax,amax,velocity_ratio,dt=.02):
        self.indices=np.asarray(indices);self.lower=np.asarray(lower);self.upper=np.asarray(upper)
        self.vmax=np.asarray(vmax);self.amax=np.asarray(amax);self.ratio=np.asarray(velocity_ratio)
        self.dt=dt;self.mode='track';self.stop=None;self.elapsed=0.;self.ready=0;self.anchor=None
        self.trajectory=CommandTrajectory(initial,self.indices,lower,upper,vmax,amax,dt)

    def step(self,actual,velocity,requested,feasible,safety,allow_resume=True):
        q=np.asarray(actual);v=np.asarray(velocity);requested=np.asarray(requested)
        trigger=not feasible or not safety['safe_to_approach']
        entry=False
        if self.mode=='track' and trigger:
            self.stop=StopTrajectory(q[self.indices],v[self.indices],self.amax,
                                     self.lower[self.indices],self.upper[self.indices])
            self.anchor=self.stop.endpoint.copy();self.elapsed=0.;self.ready=0;self.mode='brake';entry=True
        if self.mode=='track':
            command,trajectory=self.trajectory.step(requested)
            return command,dict(mode='track',phase_advance_allowed=True,entry=False,trajectory=trajectory)
        # Once entered, observed drift cannot move the captured endpoint.
        if self.mode=='brake':
            self.elapsed+=self.dt;reference,desired_velocity,_=self.stop.sample(self.elapsed)
            target=reference+self.ratio*desired_velocity
        else:target=self.anchor.copy()
        if np.any(target<self.lower[self.indices]) or np.any(target>self.upper[self.indices]):
            raise RuntimeError('stop_command_outside_joint_range')
        desired=requested.copy();desired[self.indices]=target
        command,trajectory=self.trajectory.step(desired)
        speed=float(np.max(np.abs(v[self.indices])))
        error=float(np.max(np.abs(q[self.indices]-self.anchor)))
        settled=speed<=.05 and error<=.01 and self.elapsed>=float(np.max(self.stop.duration))
        self.ready=self.ready+1 if settled and feasible and safety['safe_to_approach'] else 0
        if settled:self.mode='hold'
        diagnosis=dict(mode=self.mode,phase_advance_allowed=False,entry=entry,
                       fixed_anchor=self.anchor.copy(),elapsed=self.elapsed,trajectory=trajectory,
                       actual_speed=speed,actual_anchor_error=error,settled=settled,ready_ticks=self.ready)
        if self.mode=='hold' and self.ready>=5 and allow_resume:
            self.trajectory=CommandTrajectory(command,self.indices,self.lower,self.upper,self.vmax,self.amax,self.dt)
            self.mode='track';diagnosis['resume_next_tick']=True
        return command,diagnosis
