"""Explicit policy-output limits, without privileged action correction."""
import numpy as np

class CommandLimiter:
    def __init__(self, initial_q, bounds, dt=.05, max_rate=.5, max_acceleration=1.):
        self.q=np.asarray(initial_q,float).copy()
        self.velocity=np.zeros(7)
        self.bounds=np.asarray(bounds,float)
        self.dt,self.max_rate,self.max_acceleration=dt,max_rate,max_acceleration
        self.clipped_steps=0

    def apply(self, raw):
        raw=np.asarray(raw,float)
        if raw.shape!=(8,) or not np.isfinite(raw).all():
            raise ValueError('nonfinite_or_wrong_shape_policy_action')
        target=np.clip(raw[:7],self.bounds[:,0],self.bounds[:,1])
        desired=np.clip((target-self.q)/self.dt,-self.max_rate,self.max_rate)
        velocity=np.clip(desired,self.velocity-self.max_acceleration*self.dt,
                         self.velocity+self.max_acceleration*self.dt)
        q=self.q+velocity*self.dt
        # Do not evade the acceleration contract with an abrupt boundary clamp.
        if np.any(q<self.bounds[:,0]) or np.any(q>self.bounds[:,1]):
            raise ValueError('policy_command_reached_joint_boundary')
        action=np.r_[q,np.clip(raw[7],0.,.04)]
        self.clipped_steps+=int(not np.allclose(action,raw,rtol=0,atol=1e-10))
        self.q,self.velocity=q,velocity
        return action
