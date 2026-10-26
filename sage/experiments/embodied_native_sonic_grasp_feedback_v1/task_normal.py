"""Maintain the screened finger shape while closing actual normal-force loops."""
import numpy as np
from .task_top import Task as Previous
from .normal_admittance import update as normal_update
from .feedback import ROLES
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import evaluate,contacts,required_preload

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.normal_filtered={g:0. for g in ROLES};self.normal_targets=self.preload_targets.copy();self.normal_proposal=None
    def normal_control(self,tick,data,m):
        h=hand_ids(self.model)
        if self.group_values is None:self.group_values={g:0. for g in ROLES}
        if self.finger_reference is None:self.finger_reference=np.zeros(len(h['names']))
        if tick%5==0:
            cs,info=contacts(self.mujoco,self.model,data,True)
            self.normal_proposal=required_preload(cs,info['weight_n'],np.array(info['com_m']))
            if self.normal_proposal['feasible']:
                for g in ROLES:
                    desired=max(self.preload_targets[g],self.normal_proposal['required_group_normal_n'][g]);self.normal_targets[g]+=(1-np.exp(-.1/.15))*(desired-self.normal_targets[g])
        for g in ROLES:
            maximum=max(abs(v) for n,v in RIGHT_CLOSED.items() if group(n)==g)
            self.group_values[g],self.normal_filtered[g]=normal_update(self.group_values[g],self.normal_filtered[g],m['forces'][g],self.normal_targets[g],maximum)
        self.finger_reference=np.array([RIGHT_CLOSED.get(n,0.)*self.group_values.get(group(n),0.) for n in h['names']]);self.closure=max(self.group_values.values())
        if tick%5==0:self.events.append(dict(kind='normal_force_shape_admittance',tick=tick,stage=self.stage,measured_group_normals_n=dict(m['forces']),filtered_group_normals_n=self.normal_filtered.copy(),desired_group_normals_n=self.normal_targets.copy(),group_closures=self.group_values.copy(),static_geometry_proposal=self.normal_proposal,original_PD_gains_and_damping_preserved=True))
    def force_update(self,tick,data,m):
        return self.normal_control(tick,data,m)
    def update(self,tick,data,m):
        if self.stage!='close':return super().update(tick,data,m)
        if self.done or self.failure:return
        self.last_object_local_world=np.array(m['object_m']);self.last_object_local=m['object_local_m']
        if tick-self.start>200:self.failure='actual_group_preload_timeout';return
        if np.linalg.norm(np.array(m['object_m'])[:2]-self.case['source_object_xyz_m'][:2])>.04:self.failure='grasp_pushed_object';return
        self.normal_control(tick,data,m);self.quality=evaluate(self.mujoco,self.model,data)
        if tick%5==0:self.events.append(dict(kind='top_actual_preload',tick=tick,stage=self.stage,forces=dict(m['forces']),quality=self.quality,group_closures=self.group_values.copy()))
        ready=self.reached(tick,data) and all(m['forces'][g]>=.8*self.normal_targets[g] for g in ROLES)
        self.stable=self.stable+1 if ready else 0
        if self.stable>=5:
            pid=self.model.body('payload').id;self.feedback_start=tick;self.balance_origin=data.xipos[pid].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(self.balance_origin-data.xpos[self.wrist]);self.cup_rotation=data.xmat[pid].reshape(3,3).copy();self.change('force_balance',tick,data,m)
