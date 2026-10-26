"""Repair actual-cup alignment and finger preload; SONIC29 keeps motor authority."""
import numpy as np
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as Parent
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from .grip_groups import advance,secure,targets


class Task(Parent):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.grip_alignment_started=None;self.grip_close_started=None;self.align_stable=0
        self.grip_cup_origin=None;self.group_values=None

    def update(self,tick,data,m):
        if tick<1000:return super().update(tick,data,m)
        if self.stage!='close':
            super().update(tick,data,m)
            if self.stage not in ['close','lift','tuck','carry','target_stop','place']:return
            if self.stage!='close':
                self.group_values=advance(self.group_values,m['forces'],maximum=self.case['grip_max_closure'])
                self.closure=max(self.group_values.values())
                return
        if self.done or self.failure:return
        age=tick-self.start
        if age>self.case['stage_timeouts_ticks']['close']:
            self.failure='close_timeout';return
        if self.grip_alignment_started is None:
            self.grip_alignment_started=tick;self.grip_cup_origin=np.asarray(m['object_m']).copy()
            goal=np.asarray(m['object_m'])-np.asarray(self.case['repair_grasp_local_xyz_m'])
            self.move(tick,data,goal,np.eye(3),60)
            self.events.append(dict(kind='actual_cup_grasp_alignment',tick=tick,object_m=m['object_m'],offset_local_m=self.case['repair_grasp_local_xyz_m'],independent_body_motor_commands=False))
        if np.linalg.norm(np.asarray(m['object_m'])-self.grip_cup_origin)>.04:
            self.failure='grasp_alignment_object_displacement';return
        # Fixed measured-cup goal: do not chase an object pushed by unilateral contact.
        if self.grip_close_started is None:
            self.closure=0.
            self.align_stable=self.align_stable+1 if self.reached(tick,data) else 0
            if self.align_stable>=10:
                self.grip_close_started=tick;self.stable=0;self.group_values=dict(thumb=0.,index=0.,middle=0.)
                self.events.append(dict(kind='aligned_finger_closure_start',tick=tick))
            return
        close_age=tick-self.grip_close_started
        self.group_values=advance(self.group_values,m['forces'],maximum=self.case['grip_max_closure'])
        self.closure=max(self.group_values.values())
        ready=close_age>=75 and secure(m['forces']) and self.reached(tick,data) and m['desk_supported']
        self.stable=self.stable+1 if ready else 0
        if tick%5==0:
            self.events.append(dict(kind='contact_informed_finger_reference',tick=tick,closure=self.closure,group_closures=self.group_values.copy(),forces=m['forces'],secure=bool(ready),stable_ticks=self.stable))
        if self.stable>=25:
            self.anchor=np.asarray(m['object_local_m']);self.change('lift',tick,data,m)
            self.move(tick,data,data.xpos[self.wrist]+[0,0,.13],np.eye(3),90)

    def hand_targets(self,names):
        if self.group_values is None:
            from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
            return [RIGHT_CLOSED.get(n,0.)*self.closure for n in names]
        ratio=1.
        if self.stage=='release':ratio=self.closure/self.case['grip_closure']
        elif self.stage in ['retract','settle','done']:ratio=0.
        return targets(names,self.group_values,ratio)
