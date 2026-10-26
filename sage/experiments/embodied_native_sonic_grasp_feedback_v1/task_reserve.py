"""Restore index contact using unused original joint reference reserve."""
import numpy as np
from .task_carry import Task as Previous
from .index_reserve_control import advance
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.index_extra=0.
    def normal_control(self,tick,data,m):
        previous=None if self.finger_reference is None else self.finger_reference.copy();super().normal_control(tick,data,m)
        if tick<1362:return
        h=hand_ids(self.model);name='right_hand_index_0_joint';i=h['names'].index(name);base=float(self.finger_reference[i]);cap=RIGHT_CLOSED[name]*.5
        if self.group_values['index']>=.5-1e-12:self.index_extra=advance(self.index_extra,base,self.normal_filtered['index'],self.normal_targets['index'],cap)
        self.finger_reference[i]=base+self.index_extra
        assert self.finger_reference[i]<=cap+1e-12
        if previous is not None:assert abs(self.finger_reference[i]-previous[i])<=.006+1e-12
        if tick%5==0:self.events.append(dict(kind='native_index0_original_halfclosed_reserve',tick=tick,stage=self.stage,base_template_target_rad=base,extra_reference_rad=self.index_extra,final_target_rad=float(self.finger_reference[i]),original_reference_cap_rad=cap,actual_index_normal_n=m['forces']['index'],filtered_index_normal_n=self.normal_filtered['index'],requested_index_normal_n=self.normal_targets['index'],native_PD_and_effort_unchanged=True))
