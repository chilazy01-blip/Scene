"""Bounded P/I/velocity correction to SONIC wrist reference, never motor control."""
import numpy as np
from sage.experiments.embodied_native_sonic_transport_v1.reference_feedback import limited
class DampedReference:
    def __init__(self,previous):
        self.position=previous.position.copy();self.rotation=previous.rotation.copy();self.initialized=False;self.velocity=np.zeros(3);self.angular_velocity=np.zeros(3)
    def update(self,error,rerror,dt):
        e=np.asarray(error);r=np.asarray(rerror)
        if not np.isfinite(np.r_[e,r,self.velocity,self.angular_velocity,dt]).all() or not 0<=dt<=.100001:raise ValueError('invalid damped wrist reference')
        if not self.initialized:
            self.integral=self.position-.5*e+.15*self.velocity;self.rintegral=self.rotation-.5*r+.10*self.angular_velocity;self.initialized=True
        self.integral=limited(self.integral+.5*dt*e,.06);self.rintegral=limited(self.rintegral+.5*dt*r,.30)
        want=limited(self.integral+.5*e-.15*self.velocity,.06);rwant=limited(self.rintegral+.5*r-.10*self.angular_velocity,.30)
        self.position=limited(self.position+limited(want-self.position,.01),.06);self.rotation=limited(self.rotation+limited(rwant-self.rotation,.04),.30)
        return self.position.copy(),self.rotation.copy()
