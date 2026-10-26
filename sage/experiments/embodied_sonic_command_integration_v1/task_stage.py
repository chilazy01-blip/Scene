"""Preserve desired grasp pose at tuck by stage, including earlier successful grips."""
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.task_equilibrium import Task as Previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path

class Task(Previous):
    def move(self,tick,data,goal,rotation,duration=65):
        if self.stage=='tuck':
            p,R=self.desired(tick)
            self.path=make_path(tick,p,R,p,R,60)
            self.joint_path=None
            self.events.append(dict(kind='cartesian_path',tick=tick,origin=p.tolist(),goal=p.tolist(),rotation=R.tolist(),duration=60,origin_source='validated_grasp_desired_pose',hold_carry_preparation_pose=True,trigger='tuck_stage_independent_of_absolute_clock'))
            self.synchronize(tick,data,force=True)
            return
        return super().move(tick,data,goal,rotation,duration)
