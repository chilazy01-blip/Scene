"""Native fixed PD preload references computed separately from physical touch poses."""
import numpy as np
from .task_steady import Task as Previous
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);h=hand_ids(self.model);self.equilibrium_motor_goal=np.array([self.case['equilibrium_motor_reference_rad'].get(n,0.) for n in h['names']])
        for n,v in zip(h['names'],self.equilibrium_motor_goal):
            if n in RIGHT_CLOSED:assert min(0,RIGHT_CLOSED[n]*.5)<=v<=max(0,RIGHT_CLOSED[n]*.5)
    def normal_control(self,tick,data,m):
        if tick<980:return super().normal_control(tick,data,m)
        h=hand_ids(self.model)
        if self.finger_reference is None:self.finger_reference=np.zeros(len(h['names']))
        self.finger_reference+=np.clip(self.equilibrium_motor_goal-self.finger_reference,-.006,.006)
        self.group_values={g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in ('thumb','index','middle')};self.closure=max(self.group_values.values())
        if tick%5==0:self.events.append(dict(kind='native_equilibrium_motor_reference',tick=tick,stage=self.stage,motor_goal_rad=self.equilibrium_motor_goal.tolist(),persistent_reference_rad=self.finger_reference.tolist(),actual_group_normals_n=dict(m['forces']),physical_touch_pose_is_not_motor_reference=True,native_PD_and_effort_unchanged=True,no_external_grasp_force=True))
