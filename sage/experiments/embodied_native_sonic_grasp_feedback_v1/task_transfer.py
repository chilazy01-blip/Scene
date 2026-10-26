"""Diagnostic real loading after sustained capacity; never counts preload as grasp."""
import numpy as np
from .task_normal import Task as Previous
class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.diagnostic_capacity_ticks=0
    def update(self,tick,data,m):
        before=self.stage
        super().update(tick,data,m)
        if self.failure or self.done:return
        if before=='force_balance' and self.stage=='force_balance':
            ready=self.quality['qualified'] and self.reached(tick,data)
            self.diagnostic_capacity_ticks=self.diagnostic_capacity_ticks+1 if ready else 0
            if tick>=1194 and self.diagnostic_capacity_ticks>=15:
                pid=self.model.body('payload').id;self.anchor=np.array(m['object_local_m']);self.probe_origin=np.array(m['object_m']);self.probe_wrist=data.xpos[self.wrist].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(data.xipos[pid]-self.probe_wrist)
                self.events.append(dict(kind='diagnostic_load_despite_unqualified_preload_resultant',tick=tick,quality=self.quality,sustained_capacity_ticks=self.diagnostic_capacity_ticks,not_a_grasp_acceptance=True,post_load_acceptance_unchanged=True))
                self.change('load_probe',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.01],self.grasp_R,60)
