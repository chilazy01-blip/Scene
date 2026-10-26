"""Maintain smooth actual SONIC operation references throughout loaded phases."""
import numpy as np
from scipy.spatial.transform import Rotation
from .task_stage import Task as Previous
from .wrist_smooth import SmoothReference
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as BodyTask

class Task(Previous):
    def synchronize(self,tick,data,force=False):
        if self.path is not None and self.stage in ('loaded_hover','tuck','carry','target_stop','place','release','retract','settle'):
            if not isinstance(self.feedback,SmoothReference):
                self.feedback=SmoothReference(self.feedback)
                self.events.append(dict(kind='smooth_loaded_reference_enabled',tick=tick,stage=self.stage,initial_position_bias_m=self.feedback.position.tolist(),initial_rotation_bias_rad=self.feedback.rotation.tolist(),velocity_filter_tau_s=.12,maximum_position_bias_speed_m_s=.020,maximum_rotation_bias_speed_rad_s=.120,all29_body_actions_from_sonic=True))
            velocity=np.zeros(6)
            self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.wrist,velocity,0)
            p,R=self.desired(tick);pn,Rn=self.desired(tick+1)
            self.feedback.velocity=velocity[3:]-(pn-p)/.02
            self.feedback.angular_velocity=velocity[:3]-Rotation.from_matrix(Rn@R.T).as_rotvec()/.02
            # The parent keeps the same causal error, log and duplicate-tick
            # guard; force=True bypasses only its historical10Hz schedule.
            return BodyTask.synchronize(self,tick,data,force=True)
        return super().synchronize(tick,data,force)
