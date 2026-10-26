"""Wrench-qualified finger preload and slow real load probe; SONIC29 body."""
import numpy as np
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as Parent
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from .quality import evaluate,ROLES

class Task(Parent):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.alignment_started=None;self.alignment_stable=0;self.close_started=None;self.group_values=None;self.quality=None;self.grasp_test_passed=False;self.probe_passed=False;self.probe_origin=None;self.probe_wrist=None;self.recovery_reason=None
        self.grasp_R=np.array(self.case['loaded_grasp_rotation']);self.quality_samples=[];self.preload_targets=self.case['loaded_preload_targets_n']
    def move(self,tick,data,goal,rotation,duration=65):
        if tick>=1000:
            rotation=self.grasp_R
            if self.stage=='place':goal=np.array(self.case['target_object_xyz_m'])-rotation@np.array(self.last_object_local)
        return super().move(tick,data,goal,rotation,duration)
    def preload(self,m):
        if self.group_values is None:self.group_values={g:0. for g in ROLES}
        for g in ROLES:
            if m['forces'][g]<self.preload_targets[g]:self.group_values[g]=min(.5,self.group_values[g]+.004)
        self.closure=max(self.group_values.values())
    def recover(self,tick,data,m,reason):
        self.recovery_reason=reason;self.change('probe_lower',tick,data,m)
        self.move(tick,data,self.probe_wrist,self.grasp_R,60)
        self.events.append(dict(kind='loaded_probe_rejected',tick=tick,reason=reason,quality=self.quality))
    def update(self,tick,data,m):
        if tick<1000:return super().update(tick,data,m)
        self.last_object_local=m['object_local_m']
        controlled=('close','load_probe','lift','loaded_hover','probe_lower','probe_release','probe_settle')
        if self.stage not in controlled:
            super().update(tick,data,m)
            if self.stage in ('tuck','carry','target_stop','place'):self.preload(m)
            return
        if self.done or self.failure:return
        age=tick-self.start
        if tick%5==0 or self.quality is None:
            self.quality=evaluate(self.mujoco,self.model,data)
            self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=self.quality,group_closures=self.group_values))
        q=self.quality
        if self.stage not in ('close','probe_release','probe_settle'):self.preload(m)
        if self.stage=='close':
            if age>350:self.failure='wrench_qualified_close_timeout';return
            if self.alignment_started is None:
                self.alignment_started=tick
                self.move(tick,data,np.array(m['object_m'])-np.array(self.case['repair_grasp_local_xyz_m']),self.grasp_R,60)
                self.events.append(dict(kind='fixed_measured_cup_alignment',tick=tick,goal_m=self.path['goal'].tolist()))
            if self.close_started is None:
                self.closure=0.;self.alignment_stable=self.alignment_stable+1 if self.reached(tick,data) else 0
                if self.alignment_stable>=10:self.close_started=tick
                return
            self.preload(m)
            if np.linalg.norm(np.array(m['object_m'])[:2]-np.array(self.case['source_object_xyz_m'])[:2])>.04:self.failure='grasp_pushed_object';return
            ready=tick-self.close_started>=75 and self.reached(tick,data) and m['desk_supported'] and q['qualified']
            self.stable=self.stable+1 if ready else 0
            if self.stable>=15:
                self.anchor=np.array(m['object_local_m']);self.probe_origin=np.array(m['object_m']);self.probe_wrist=data.xpos[self.wrist].copy()
                self.change('load_probe',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.01],self.grasp_R,60)
        elif self.stage=='load_probe':
            slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
            if slip>.008:self.recover(tick,data,m,'probe_relative_slip');return
            if age>=75:
                ready=(m['object_m'][2]-self.probe_origin[2]>=.006 and not m['desk_supported'] and q['hand_force_world_n'][2]>=.8*q['weight_n'] and q['qualified'] and slip<=.006)
                if not ready:self.recover(tick,data,m,'probe_load_not_transferred');return
                self.probe_passed=True;self.change('lift',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.05],self.grasp_R,90)
        elif self.stage in ('lift','loaded_hover'):
            slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
            if slip>.015:self.recover(tick,data,m,'loaded_relative_slip');return
            ready=not m['desk_supported'] and m['object_bottom_m']>self.case['support_top_m']+.025 and q['qualified'] and q['hand_force_world_n'][2]>=.8*q['weight_n']
            if self.stage=='lift':
                if age>170:self.recover(tick,data,m,'real_lift_not_qualified');return
                if self.reached(tick,data) and ready:self.change('loaded_hover',tick,data,m)
            else:
                self.stable=self.stable+1 if ready else 0
                if age>150:self.recover(tick,data,m,'loaded_hover_unstable');return
                if self.stable>=50:
                    self.grasp_test_passed=True;self.events.append(dict(kind='loaded_hover_passed',tick=tick,time_s=float(data.time)))
                    self.object_lift_origin=np.array(m['object_m']);self.change('tuck',tick,data,m);self.move(tick,data,data.qpos[:3]+np.array(self.case['ready_arm_relative_m']),self.grasp_R,90)
        elif self.stage=='probe_lower':
            if age>=75 and m['desk_supported']:self.change('probe_release',tick,data,m);self.release_values=self.group_values.copy()
            elif age>150:self.failure='probe_recovery_not_supported'
        elif self.stage=='probe_release':
            self.group_values={g:v*(1-float(smooth(age/60))) for g,v in self.release_values.items()};self.closure=max(self.group_values.values())
            if age>=70:self.change('probe_settle',tick,data,m)
        elif self.stage=='probe_settle':
            if age>=50:self.failure=self.recovery_reason
    def hand_targets(self,names):
        if self.group_values is None:return [RIGHT_CLOSED.get(n,0.)*self.closure for n in names]
        ratio=self.closure/self.case['grip_closure'] if self.stage=='release' else (0. if self.stage in ('retract','settle','done') else 1.)
        return [RIGHT_CLOSED.get(n,0.)*self.group_values.get(group(n),0.)*ratio for n in names]
