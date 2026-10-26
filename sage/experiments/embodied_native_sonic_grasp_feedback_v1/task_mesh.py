"""Mesh-planned manipulation references with native PD and measured preload control."""
import numpy as np
from .task_top import Task as Previous
from .normal_admittance import update as normal_update
from .hold_floor import project
from .mesh_hand_reference import targets,ROLES
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import evaluate,contacts,required_preload

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.mesh_template=self.case['mesh_finger_template'];self.normal_filtered={g:0. for g in ROLES};self.normal_targets=self.preload_targets.copy();self.loaded_grip_floor=None;self.normal_proposal=None
    def normal_control(self,tick,data,m):
        h=hand_ids(self.model)
        if self.group_values is None:self.group_values={g:0. for g in ROLES}
        old=self.group_values.copy()
        if self.quality is not None and self.quality['qualified'] and self.loaded_grip_floor is None:
            self.loaded_grip_floor=old.copy();self.events.append(dict(kind='mesh_grasp_actual_capacity_reference_latch',tick=tick,closures=old.copy(),qualified_actual_geometry=True,not_grasp_acceptance=True))
        if tick%5==0:
            cs,info=contacts(self.mujoco,self.model,data,True);self.normal_proposal=required_preload(cs,info['weight_n'],np.array(info['com_m']))
            if self.normal_proposal['feasible']:
                for g in ROLES:
                    request=max(self.preload_targets[g],self.normal_proposal['required_group_normal_n'][g]);self.normal_targets[g]+=(1-np.exp(-.1/.15))*(request-self.normal_targets[g])
        for g in ROLES:
            maximum=max(abs(v) for n,v in self.mesh_template.items() if group(n)==g);self.group_values[g],self.normal_filtered[g]=normal_update(self.group_values[g],self.normal_filtered[g],m['forces'][g],self.normal_targets[g],maximum)
        if self.loaded_grip_floor is not None:
            self.group_values=project(old,self.group_values,self.loaded_grip_floor);self.loaded_grip_floor=self.group_values.copy()
        self.finger_reference=targets(h['names'],self.mesh_template,self.group_values);self.closure=max(self.group_values.values())
        if tick%5==0:self.events.append(dict(kind='native_mesh_measured_normal_control',tick=tick,stage=self.stage,group_closures=self.group_values.copy(),measured_group_normals_n=dict(m['forces']),filtered_group_normals_n=self.normal_filtered.copy(),desired_group_normals_n=self.normal_targets.copy(),reference_floor=None if self.loaded_grip_floor is None else self.loaded_grip_floor.copy(),native_contact_allocation=self.normal_proposal,hand_target_rad=self.finger_reference.tolist()))
    def force_update(self,tick,data,m):return self.normal_control(tick,data,m)
    def update(self,tick,data,m):
        if self.stage not in ('close','force_balance'):return super().update(tick,data,m)
        if self.done or self.failure:return
        self.last_object_local_world=np.array(m['object_m']);self.last_object_local=m['object_local_m'];pid=self.model.body('payload').id;age=tick-self.start
        if np.linalg.norm(np.array(m['object_m'])[:2]-self.case['source_object_xyz_m'][:2])>.04:self.failure='grasp_pushed_object';return
        if age>200:self.failure='mesh_'+self.stage+'_timeout';return
        if tick%5==0 or self.quality is None:
            self.quality=evaluate(self.mujoco,self.model,data);self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=self.quality,group_closures=None if self.group_values is None else self.group_values.copy()))
        self.normal_control(tick,data,m)
        if self.stage=='close':
            ready=self.reached(tick,data) and all(m['forces'][g]>=.8*self.normal_targets[g] for g in ROLES);self.stable=self.stable+1 if ready else 0
            if self.stable>=5:
                self.feedback_start=tick;self.balance_origin=data.xipos[pid].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(self.balance_origin-data.xpos[self.wrist]);self.cup_rotation=data.xmat[pid].reshape(3,3).copy();self.change('force_balance',tick,data,m)
        else:
            ready=self.quality['qualified'] and self.reached(tick,data);self.stable=self.stable+1 if ready else 0
            if self.stable>=15:
                self.anchor=np.array(m['object_local_m']);self.probe_origin=np.array(m['object_m']);self.probe_wrist=data.xpos[self.wrist].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(data.xipos[pid]-self.probe_wrist)
                self.events.append(dict(kind='native_mesh_diagnostic_load_trial',tick=tick,quality=self.quality,strict_postload_and_task_gates_unchanged=True,not_grasp_acceptance=True));self.change('load_probe',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.01],self.grasp_R,60)
