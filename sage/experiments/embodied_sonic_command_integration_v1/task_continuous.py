"""Retain original placement/retract goals without resetting their desired origin."""
import numpy as np
from .task_joint import Task as Previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path

class Task(Previous):
    def move(self,tick,data,goal,rotation,duration=65):
        if self.stage in ('place','retract'):
            position,R=self.desired(tick)
            if self.stage=='place':
                goal=np.asarray(self.case['target_object_xyz_m'])-self.grasp_R@np.asarray(self.last_object_local)
                duration=65
            else:duration=40
            self.path=make_path(tick,position,R,goal,self.grasp_R,duration);self.joint_path=None
            self.events.append(dict(kind='cartesian_path',tick=tick,origin=position.tolist(),goal=np.asarray(goal).tolist(),rotation=self.grasp_R.tolist(),duration=duration,origin_source='previous_desired_reference',original_place_or_retract_goal_preserved=True))
            self.synchronize(tick,data,force=True)
            return
        return super().move(tick,data,goal,rotation,duration)
