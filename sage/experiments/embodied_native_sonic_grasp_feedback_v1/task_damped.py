import numpy as np
from .task_ff import Task as Previous
from .wrist_damping import DampedReference
class Task(Previous):
    def synchronize(self,tick,data,force=False):
        if tick>=1194:
            if not isinstance(self.feedback,DampedReference):self.feedback=DampedReference(self.feedback)
            v=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.wrist,v,0);self.feedback.velocity=v[3:].copy();self.feedback.angular_velocity=v[:3].copy()
        return super().synchronize(tick,data,force)
