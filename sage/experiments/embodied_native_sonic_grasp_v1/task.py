"""Repair actual-cup alignment and finger preload; SONIC29 keeps motor authority."""
import numpy as np
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as Parent
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth
from .grip import preload,secure


class Task(Parent):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.grip_alignment_started=None;self.grip_close_started=None;self.align_stable=0
        self.grip_cup_origin=None

    def update(self,tick,data,m):
        if tick<1000:return super().update(tick,data,m)
        if self.stage!='close':
            super().update(tick,data,m)
            if self.stage not in ['close','lift','tuck','carry','target_stop','place']:return
            if self.stage!='close':
                self.closure=preload(self.closure,m['forces'],.02,maximum=self.case['grip_max_closure'],rate=.15)
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
        # The virtual wrist reference follows the measured cup center, no physical state writes.
        self.path['goal']=np.asarray(m['object_m'])-np.asarray(self.case['repair_grasp_local_xyz_m'])
        if self.grip_close_started is None:
            self.closure=0.
            self.align_stable=self.align_stable+1 if self.reached(tick,data) else 0
            if self.align_stable>=10:
                self.grip_close_started=tick;self.stable=0
                self.events.append(dict(kind='aligned_finger_closure_start',tick=tick))
            return
        close_age=tick-self.grip_close_started
        self.closure=max(self.closure,.30*float(smooth(close_age/75)))
        if close_age>=75:self.closure=preload(self.closure,m['forces'],.02,maximum=self.case['grip_max_closure'])
        ready=close_age>=75 and secure(m['forces']) and self.reached(tick,data) and m['desk_supported']
        self.stable=self.stable+1 if ready else 0
        if tick%5==0:
            self.events.append(dict(kind='contact_informed_finger_reference',tick=tick,closure=self.closure,forces=m['forces'],secure=bool(ready),stable_ticks=self.stable))
        if self.stable>=20:
            self.anchor=np.asarray(m['object_local_m']);self.change('lift',tick,data,m)
            self.move(tick,data,data.xpos[self.wrist]+[0,0,.13],np.eye(3),90)
