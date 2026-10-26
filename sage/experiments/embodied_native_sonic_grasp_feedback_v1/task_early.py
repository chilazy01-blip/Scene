"""Keep the established grasp impedance while applying the real load trial."""
import numpy as np
from .task_transfer import Task as Previous
from .hold_floor import project
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.loaded_grip_floor=None
    def normal_control(self,tick,data,m):
        active=tick>=1180 and self.stage not in ('release','retract','settle','done')
        if not active:return super().normal_control(tick,data,m)
        if self.loaded_grip_floor is None:
            self.loaded_grip_floor=self.group_values.copy();self.events.append(dict(kind='capture_loaded_grip_reference_floor',tick=tick,closures=self.loaded_grip_floor.copy(),source='actual persistent targets before the load trial, no current-q overwrite'))
        old=self.group_values.copy();start=len(self.events);super().normal_control(tick,data,m);proposal=self.group_values.copy();self.group_values=project(old,proposal,self.loaded_grip_floor);self.loaded_grip_floor=self.group_values.copy()
        h=hand_ids(self.model);self.finger_reference=np.array([RIGHT_CLOSED.get(n,0)*self.group_values.get(group(n),0) for n in h['names']]);self.closure=max(self.group_values.values())
        for e in self.events[start:]:
            if e.get('kind')=='normal_force_shape_admittance':e['kind']='normal_force_shape_admittance_before_hold_floor'
        if tick%5==0:self.events.append(dict(kind='loaded_grip_reference_floor',tick=tick,stage=self.stage,previous_closures=old,proposed_closures=proposal,actual_closures=self.group_values.copy(),floor=self.loaded_grip_floor.copy(),hand_target_rad=self.finger_reference.tolist(),original_PD_and_native_limits_unchanged=True))
