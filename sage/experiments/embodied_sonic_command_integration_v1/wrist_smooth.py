"""Same bounded reference P/I/velocity terms with filtered velocity and time-based slew."""
import numpy as np
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.wrist_damping import DampedReference
from sage.experiments.embodied_native_sonic_transport_v1.reference_feedback import limited

class SmoothReference(DampedReference):
    def update(self,error,rerror,dt):
        e=np.asarray(error,dtype=float);r=np.asarray(rerror,dtype=float)
        if e.shape!=(3,) or r.shape!=(3,) or not np.isfinite(np.r_[e,r,self.velocity,self.angular_velocity,dt]).all() or not 0<=dt<=.100001:raise ValueError('invalid smooth reference observation')
        if not self.initialized:
            self.filtered_v=self.velocity.copy();self.filtered_w=self.angular_velocity.copy()
            self.integral=self.position-.5*e+.15*self.filtered_v
            self.rintegral=self.rotation-.5*r+.10*self.filtered_w
            self.initialized=True
            return self.position.copy(),self.rotation.copy()
        alpha=1-np.exp(-dt/.12)
        self.filtered_v+=alpha*(self.velocity-self.filtered_v)
        self.filtered_w+=alpha*(self.angular_velocity-self.filtered_w)
        self.integral=limited(self.integral+.5*dt*e,.06)
        self.rintegral=limited(self.rintegral+.5*dt*r,.30)
        want=limited(self.integral+.5*e-.15*self.filtered_v,.06)
        rwant=limited(self.rintegral+.5*r-.10*self.filtered_w,.30)
        self.position=limited(self.position+limited(want-self.position,.020*dt),.06)
        self.rotation=limited(self.rotation+limited(rwant-self.rotation,.120*dt),.30)
        return self.position.copy(),self.rotation.copy()
