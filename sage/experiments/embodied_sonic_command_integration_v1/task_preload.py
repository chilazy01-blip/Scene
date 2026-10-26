"""Connect the existing post-transfer preload target to the native hand PD references."""
import numpy as np
from .task_smooth import Task as Previous
from .preload_tracking import advance,ROLES
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

class Task(Previous):
    def normal_control(self,tick,data,m):
        active=self.loaded_balance_started is not None and self.stage in ('lift','loaded_hover','tuck','carry','target_stop','place')
        if not active:return super().normal_control(tick,data,m)
        if not hasattr(self,'tracking_goals'):
            self.tracking_goals={g:max(float(self.normal_targets[g]),float(m['forces'][g])) for g in ROLES}
            self.tracking_filtered={g:float(m['forces'][g]) for g in ROLES}
            self.events.append(dict(kind='native_loaded_preload_tracking_enabled',tick=tick,targets_n=self.tracking_goals.copy(),source='existing_actual_transfer_loaded_preload_adjustment',original_finger_PD_effort_bounds_and_task_gates=True))
        h=hand_ids(self.model)
        self.finger_reference,self.tracking_filtered=advance(self.finger_reference,h['names'],m['forces'],self.tracking_goals,self.tracking_filtered)
        self.group_values={g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in ROLES};self.closure=max(self.group_values.values())
        if tick%5==0:self.events.append(dict(kind='native_loaded_preload_tracking',tick=tick,stage=self.stage,measured_group_normals_n=dict(m['forces']),filtered_group_normals_n=self.tracking_filtered.copy(),targets_n=self.tracking_goals.copy(),persistent_reference_rad=self.finger_reference.tolist(),maximum_delta_rad_per20ms=.006,preload_not_unloaded_before_release=True))
