"""Preserve measured loaded support and plan enough lift clearance for native cup tilt."""
import numpy as np
from .task_mesh import Task as Previous
from .balanced_preload import solve,ROLES
from .continuous_lift import make_path
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import contacts,evaluate

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.loaded_balance_started=None;self.loaded_balance_targets=None
    def update(self,tick,data,m):
        if self.stage=='load_probe' and tick-self.start>=70:
            if self.done or self.failure:return
            self.last_object_local_world=np.array(m['object_m']);self.last_object_local=m['object_local_m']
            if tick%5==0 or self.quality is None:
                self.quality=evaluate(self.mujoco,self.model,data);self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=self.quality,group_closures=self.group_values.copy()))
            self.force_update(tick,data,m);q=self.quality;slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
            if slip>.008:self.recover(tick,data,m,'probe_relative_slip');return
            ready=m['object_m'][2]-self.probe_origin[2]>=.006 and not m['desk_supported'] and q['hand_force_world_n'][2]>=.8*q['weight_n'] and q['qualified'] and slip<=.006
            if not ready:self.recover(tick,data,m,'probe_load_not_transferred');return
            self.probe_passed=True;rows,info=contacts(self.mujoco,self.model,data);observed={g:sum(c['normal_n'] for c in rows if c['role']==g) for g in ROLES};minimum={g:max(1.5,observed[g]) for g in ROLES};allocation=solve(rows,info['weight_n'],np.array(info['com_m']),minimum)
            if not allocation['feasible']:self.recover(tick,data,m,'loaded_preload_balance_infeasible');return
            self.preload_targets={g:max(self.preload_targets[g],allocation['group_normals_n'][g]) for g in ROLES};self.normal_targets=self.preload_targets.copy();self.loaded_balance_targets=self.preload_targets.copy();self.loaded_balance_started=tick
            self.events.append(dict(kind='actual_transfer_passed_loaded_preload_adjustment',tick=tick,actual_group_normals_n=observed,allocation=allocation,targets_n=self.preload_targets.copy(),hand_references_rate_limited=True,no_wrist_reference_reset=True));position,rotation=self.desired(tick);self.change('lift',tick,data,m);self.joint_path=None;self.path=make_path(tick,position,rotation,self.probe_wrist+[0,0,.075],self.grasp_R,98);self.events.append(dict(kind='cartesian_path',tick=tick,origin=self.path['origin'].tolist(),goal=self.path['goal'].tolist(),rotation=self.path['R'].tolist(),duration=98,origin_source='previous_desired_reference',original_probe_to_lift_workflow=True));self.synchronize(tick,data,force=True);return
        return super().update(tick,data,m)
