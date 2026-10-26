"""Reference-only manipulation; all29 body actions remain SONIC outputs."""
import numpy as np
from scipy.spatial.transform import Rotation
from .planner_v3 import ArmPlanner
from sage.experiments.embodied_native_object_transport_v1.task_v5 import Task as ParentTask
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_data_stability_v1 import sonic_native_dynamic_shadow as native


class Task(ParentTask):
    def ready_arm(self,tick,data):
        goal=data.qpos[:3]+np.asarray(self.case['ready_arm_relative_m'])
        fit=self.ik.solve(data.qpos,goal,np.eye(3),max_evaluations=150)
        if fit['position_error_m']>.01 or fit['orientation_error_rad']>.05:
            self.failure='ready_arm_reference_unreachable';return
        plan=ArmPlanner(self.mujoco,self.model,self.armq).solve(data.qpos,fit['angles_rad'])
        self.events.append(dict(kind='reference_only_collision_route',tick=tick,goal_m=goal.tolist(),plan=plan))
        if not plan['passed']:
            self.failure='reference_route_not_found';return
        knots=np.asarray(plan['knots_rad'])
        # Quintic interpolation: peak joint reference speed <=0.5rad/s.
        durations=[max(20,int(np.ceil(1.875*np.max(np.abs(b-a))/(.5*.02)))) for a,b in zip(knots[:-1],knots[1:])]
        duration=sum(durations)
        if duration>600:
            self.failure='bounded_reference_route_duration';return
        self.path=None
        self.joint_path=dict(tick=tick,duration=duration,target=np.array(fit['angles_rad']),goal_m=goal.copy(),R=np.eye(3))
        cursor=tick
        for a,b,n in zip(knots[:-1],knots[1:],durations):
            f=smooth(np.arange(n)/n)[:,None]
            self.q[cursor:cursor+n,ARM+7]=(1-f)*a+f*b;cursor+=n
        self.q[cursor:,ARM+7]=knots[-1]
        self.v=native._reference_velocities(self.q)
        self.events.append(dict(kind='sonic29_manipulation_reference',tick=tick,segment_ticks=durations,duration=duration,
            independent_arm_actuation=False,knots_rad=knots.tolist()))

    def reached(self,tick,data):
        if self.joint_path is not None and 'goal_m' in self.joint_path:
            p=self.joint_path
            error=float(np.linalg.norm(data.xpos[self.wrist]-p['goal_m']))
            angle=float(np.linalg.norm(Rotation.from_matrix(p['R'].T@data.xmat[self.wrist].reshape(3,3)).as_rotvec()))
            return tick>=p['tick']+p['duration'] and error<.025 and angle<.15
        return super().reached(tick,data)
