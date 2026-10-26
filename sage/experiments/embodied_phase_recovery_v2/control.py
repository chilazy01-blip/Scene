"""Native-command expert matching live goals, coupled recovery, and safe withdrawal."""
import copy
import hashlib
import json
import numpy as np
from scipy.spatial.transform import Rotation
from dataclasses import asdict
from sage.experiments.embodied_phase_coordinator_v1.coordinator import Coordinator,Observation,Goal,CoordinationRejected
from sage.experiments.embodied_phase_coordinator_v1.native_packet import packet
from sage.experiments.embodied_milestone_v1.control import Expert
from sage.experiments.embodied_collision_expert_v2.planner_interior import collision_roles
from .recovery import preview
from .withdrawal import reference as withdraw,motion_ticks,interpolate

class Clock(Coordinator):
    def restore(self,state):
        if type(state.get('done')) is not bool or state.get('failure') not in (None,'unsafe_or_out_of_domain','total_duration','phase_recovery_timeout','phase_tracking_timeout'):raise CoordinationRejected('checkpoint_terminal_type')
        super().restore(copy.deepcopy(state))
    def step(self,observation,goal,*,advance_allowed=True,recovery_goal=None,recovery_certified=False):
        before=self.local_tick
        value=super().step(observation,goal,recovery_goal=recovery_goal,recovery_certified=recovery_certified)
        if not advance_allowed and not value['phase_advanced'] and self.local_tick>before:
            self.local_tick=before;self.extra_ticks+=1
            if self.extra_ticks>self.MAX_EXTRA_TICKS:
                self.extra_ticks=self.MAX_EXTRA_TICKS;self.failure='phase_tracking_timeout';raise CoordinationRejected(self.failure)
        value['tracking_hold']=not advance_allowed;return value

class RecoveryExpert(Expert):
    def __init__(self,context,stages,intent,envelope,library,withdrawal_goal):
        super().__init__(context,stages,intent,envelope);self.clock=Clock(stages)
        self.library=library;self.withdrawal_goal=np.asarray(withdrawal_goal);self.withdraw_start=None;self.withdraw_ticks=None;self.withdraw_elapsed=0;self.lower_attempted=False;self.lower_certificate=None
    def snapshot(self):
        value=super().snapshot();value.update(withdraw_start=None if self.withdraw_start is None else self.withdraw_start.tolist(),withdraw_ticks=self.withdraw_ticks,withdraw_elapsed=self.withdraw_elapsed,lower_attempted=self.lower_attempted,lower_certificate=copy.deepcopy(self.lower_certificate));return value
    def restore(self,state):
        if type(state['withdraw_elapsed']) is not int or not 0<=state['withdraw_elapsed']<=7450 or type(state['lower_attempted']) is not bool:raise CoordinationRejected('recovery_checkpoint_counters')
        if state['withdraw_ticks'] is not None and (type(state['withdraw_ticks']) is not int or not 275<=state['withdraw_ticks']<=424):raise CoordinationRejected('withdraw_checkpoint_duration')
        if state['withdraw_start'] is not None:
            q=np.asarray(state['withdraw_start'])
            if q.shape!=(43,) or not np.isfinite(q).all() or np.any(q<self.c.lower-.03-1e-9) or np.any(q>self.c.upper+.03+1e-9):raise CoordinationRejected('withdraw_checkpoint_observed_state')
        super().restore({k:state[k] for k in ['clock','reference','centers0','rotations0']})
        self.withdraw_start=None if state['withdraw_start'] is None else np.asarray(state['withdraw_start']);self.withdraw_ticks=state['withdraw_ticks'];self.withdraw_elapsed=state['withdraw_elapsed'];self.lower_attempted=state['lower_attempted'];self.lower_certificate=copy.deepcopy(state['lower_certificate'])
    def step(self,tick,task_ready,geometry_safe):
        c=self.c;stage=self.clock.stage;logical=self.stages[self.clock.stage_index][1]+self.clock.local_tick*.02;v=self.intent(c,logical,self.centers0,self.rotations0);arm=self.planner.arm
        residual=c.d.qpos[c.qpos]-self.reference;mask=~np.isin(np.arange(43),c.lower_indices);lo=np.minimum(0.,self.envelope['joint_error_min']);hi=np.maximum(0.,self.envelope['joint_error_max'])
        yaw=Rotation.from_quat(c.d.qpos[[4,5,6,3]]).as_euler('xyz')[2];delta=c.d.qpos[:2]-[v['planned_x'],v['planned_y']];yaw_error=abs(np.arctan2(np.sin(yaw-v['heading']),np.cos(yaw-v['heading'])))
        domain=abs(delta[0])<=.04+1e-9 and abs(delta[1])<=.08+1e-9 and yaw_error<=.04+self.envelope['rpy_abs_max'][2]+1e-9 and abs(c.d.qpos[2]-self.clock.last_height)<=.05 and np.all(residual[mask]>=lo[mask]-1e-9) and np.all(residual[mask]<=hi[mask]+1e-9)
        withdrawing=stage in ['retract','rise_empty','settle_final']
        if withdrawing:
            if self.withdraw_start is None:
                self.withdraw_start=c.d.qpos[c.qpos].copy();self.withdraw_ticks=motion_ticks(self.withdraw_start,self.withdrawal_goal,arm)
            elapsed=self.withdraw_elapsed if stage=='retract' else self.withdraw_ticks
            desired=interpolate(self.withdraw_start,self.withdrawal_goal,elapsed,self.withdraw_ticks,arm)
            ref,pred,goals,meta=withdraw(c,self.reference,desired,v['hand']);bad=meta['bad']
        else:
            ref,meta=self.planner.step(c.d.qpos,self.reference,v['centers'],v['rotations'],v['hand'],v['grasp']);goals=v['centers'];bad,_=collision_roles(c,self.planner.config.data,v['grasp'])
        if bad:raise CoordinationRejected('predicted_forbidden_geometry')
        actual=[c.d.geom_xpos[c.m.geom('gripper0_'+s+'_g0_col').id] for s in ['left','right']];error=max(float(np.linalg.norm(a-b)) for a,b in zip(actual,goals))
        calibrated_height=float(self.library.at(v['height'],'nominal')[2]);goal=Goal((v['planned_x'],v['planned_y']),v['heading'],v['height'],calibrated_height);recovery=None;certificate=None
        endpoint=self.clock.local_tick==self.clock.stages[self.clock.stage_index][1]-1
        if endpoint and self.clock.extra_ticks>=150 and error>.006 and stage in ['reach','close','rise_lift','carry','stop_target','lower_place','release'] and not self.lower_attempted:
            self.lower_attempted=True
            mode=min(['nominal','low','high'],key=lambda name:abs(float(self.library.at(v['height'],name)[2])-c.d.qpos[2]))
            candidate=('lower',0.,0.,-.04)
            if v['height']<.68-1e-12:
                heading=Rotation.from_euler('z',v['heading']).as_matrix()[:2,:2]
                target=np.array([v['planned_x'],v['planned_y']])+heading@np.array([.04,0.])
                shift=heading.T@(target-c.d.qpos[:2]);candidate=('forward',float(shift[0]),float(shift[1]),0.)
            trial,qs,rs,rows=preview(c,self.library,c.d.qpos.copy(),self.reference,v['centers'],v['rotations'],v['hand'],v['grasp'],v['height'],v['heading'],candidate,mode=mode)
            certificate=dict(mode=mode,result=trial,states_sha256=hashlib.sha256(np.asarray(qs).tobytes()).hexdigest(),reference_before=self.reference.tolist(),qpos_before=c.d.qpos.tolist());self.lower_certificate=certificate
            if trial['passed']:recovery=Goal(tuple(trial['target_xy']),v['heading'],trial['height_command'],trial['root_height'])
        observation=Observation(tick,tuple(c.d.qpos[:2]),float(yaw),float(c.d.qpos[2]),float(np.linalg.norm(c.d.qvel[:3])),error,bool(task_ready and (not withdrawing or self.withdraw_elapsed>=self.withdraw_ticks)),bool(geometry_safe),bool(domain))
        pacing=abs(delta[0])<=.03 and abs(delta[1])<=.06 and error<=.012
        command=self.clock.step(observation,goal,advance_allowed=pacing,recovery_goal=recovery,recovery_certified=recovery is not None)
        if stage=='retract':self.withdraw_elapsed+=1
        if command['phase_advanced']:self.lower_attempted=False;self.lower_certificate=None
        self.reference=ref
        return packet(command,ref),dict(command=command,logical_time=logical,measured_palm_error=error,predicted=meta,grasp=v['grasp'],desired_object_pose=v['object_pose'].tolist(),domain=bool(domain),withdrawal=bool(withdrawing),lower_certificate=certificate,root_height_goal=calibrated_height)
