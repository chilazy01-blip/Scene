"""Correct the measured missing-index/excess-middle preload in trial01."""
import numpy as np
from .task_body import Task as Previous
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group


class Task(Previous):
    def normal_control(self,tick,data,m):
        if tick<980 or not self.body_realign_done:return super().normal_control(tick,data,m)
        roles=('thumb','index','middle');h=hand_ids(self.model);ratio=self.case['loaded_native_reference_ratio']
        if not hasattr(self,'tracking_filtered'):
            self.tracking_filtered={g:float(m['forces'][g]) for g in roles}
        self.tracking_goals={g:float(self.normal_targets[g]) for g in roles}
        alpha=1-np.exp(-.02/.05)
        previous=self.finger_reference.copy()
        for g in roles:self.tracking_filtered[g]+=alpha*(m['forces'][g]-self.tracking_filtered[g])
        for i,n in enumerate(h['names']):
            if n not in RIGHT_CLOSED:continue
            g=group(n);error=self.tracking_goals[g]-self.tracking_filtered[g]
            if abs(error)<.05:error=0.
            delta=np.sign(RIGHT_CLOSED[n])*np.clip(.02*.1*error,-.006,.006)
            end=RIGHT_CLOSED[n]*ratio;native=self.model.joint(n).range
            self.finger_reference[i]=np.clip(self.finger_reference[i]+delta,max(min(0,end),native[0]),min(max(0,end),native[1]))
        self.group_values={g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in roles};self.closure=max(self.group_values.values())
        assert np.max(np.abs(self.finger_reference-previous))<=.006+1e-12
        if tick%5==0:self.events.append(dict(kind='bidirectional_body_preload_feedback',tick=tick,stage=self.stage,normal_goals_n=self.tracking_goals.copy(),measured_normals_n=dict(m['forces']),filtered_normals_n=self.tracking_filtered.copy(),reference_rad=self.finger_reference.tolist(),each_reference_delta_max_rad=.006,native_model_PD_effort_unchanged=True))
