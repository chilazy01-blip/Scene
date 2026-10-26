"""Prospective causal emission of a frozen whole path, without state writes.

The eight component ranges form one continuous physical history. They are not
independent episodes, and passing them cannot substitute for the full task.
"""
import math
import numpy as np
from sage.experiments.embodied_reference_transition_v1.admission import TrackingDomain
from sage.experiments.embodied_task_space_v6.causal_body_r1 import BodyHistory
from sage.experiments.embodied_task_space_v9.whole_geometry_gate_r1 import STAGES

COMPONENT_PHASES=((0,2),(2,4),(4,6),(6,8),(8,9),(9,11),(11,13),(13,15))

class CausalReferenceRejected(ValueError):pass

class CausalReference:
    def __init__(self, arrays, goals, nominal, names, qpos_addresses, lower_indices, envelope):
        self.a=arrays;self.goals=np.asarray(goals);self.nominal=np.asarray(nominal)
        self.qadr=np.asarray(qpos_addresses);self.active=np.asarray(arrays['active'])
        self.offsets=np.asarray(arrays['offsets']);self.n=len(arrays['reference'])
        if self.n!=7450 or self.goals.shape!=(self.n,4):raise ValueError('nominal_full_reference_clock')
        if np.any(self.active[np.asarray(lower_indices)]):raise ValueError('policy_lower_reference_override')
        self.domain_envelope=envelope
        self.domain=TrackingDomain(np.minimum(0.,envelope['joint_error_min']),np.maximum(0.,envelope['joint_error_max']),self.active,names)
        self.previous=self.nominal.copy();self.velocity=np.zeros(43);self.next_tick=0;self.body=BodyHistory();self.stable=[0]*15;self.done=False
    def snapshot(self):
        return dict(next_tick=self.next_tick,previous_reference=self.previous.tolist(),previous_velocity=self.velocity.tolist(),body=self.body.snapshot(),phase_stable=self.stable.copy(),done=self.done)
    def step(self,tick,qpos,palm_positions,base_speed,task_ready,geometry_safe):
        if self.done or tick!=self.next_tick or tick>=self.n:raise CausalReferenceRejected('causal_tick_or_closed')
        qpos=np.asarray(qpos);palm_positions=np.asarray(palm_positions)
        if qpos.shape!=self.a['qpos'][tick].shape or palm_positions.shape!=(2,3) or not np.isfinite(qpos).all():raise CausalReferenceRejected('observation_shape_or_finite')
        phase=int(np.searchsorted(self.offsets[1:],tick,side='right'));stage=STAGES[phase];goal=self.goals[tick]
        proposed=self.nominal.copy();proposed[self.active]=self.a['reference'][tick]
        emission=self.domain.assess(qpos[self.qadr],self.previous,proposed)
        if not emission['current_inside']:raise CausalReferenceRejected('observed_tracking_out_of_domain')
        if not emission['emission_inside']:raise CausalReferenceRejected('reference_jump_out_of_domain')
        velocity=(proposed-self.previous)/.02;acceleration=(velocity-self.velocity)/.02
        if np.max(abs(velocity[self.active]))>.35+2e-7 or np.max(abs(acceleration[self.active]))>.5+2e-6:raise CausalReferenceRejected('causal_reference_rate_or_history')
        w,x,y,z=qpos[3:7];yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z));dq=qpos[:3]-self.a['qpos'][tick,:3]
        expected=self.a['qpos'][tick,3:7];w,x,y,z=expected;expected_yaw=math.atan2(2*(w*z+x*y),1-2*(y*y+z*z));yaw_error=abs(math.atan2(math.sin(yaw-expected_yaw),math.cos(yaw-expected_yaw)))
        domain=abs(dq[0])<=.04+1e-9 and abs(dq[1])<=.08+1e-9 and abs(dq[2])<=.05+1e-9 and yaw_error<=.04+envelope_yaw(self.domain_envelope)
        # The original measured yaw envelope is added explicitly by the factory.
        if not geometry_safe or not domain:raise CausalReferenceRejected('physical_geometry_or_body_domain')
        body=self.body.step(tick,qpos[:2],yaw,goal[:2],goal[2],goal[3])
        palm_error=float(np.linalg.norm(palm_positions-self.a['goals'][tick],axis=1).max())
        pose_ready=np.linalg.norm(qpos[:2]-goal[:2])<=.01 and abs(math.atan2(math.sin(yaw-goal[2]),math.cos(yaw-goal[2])))<=.01 and abs(qpos[2]-self.a['qpos'][tick,2])<=.015 and base_speed<=.05
        ready=pose_ready and palm_error<=.006 and task_ready
        if tick>=self.offsets[phase+1]-25:self.stable[phase]=self.stable[phase]+1 if ready else 0
        if tick==self.offsets[phase+1]-1 and self.stable[phase]<25:raise CausalReferenceRejected('phase_endpoint_not_ready:'+stage)
        packet=dict(tick=tick,dt=.02,frame='body_heading',units='SI_rad',q_reference=proposed.tolist(),**body)
        self.previous=proposed;self.velocity=velocity;self.next_tick+=1;self.done=self.next_tick==self.n
        return packet,dict(stage=stage,tick=tick,phase=phase,task_ready=bool(task_ready),measured_palm_error_m=palm_error,body_domain=bool(domain),emission=emission,reference_index=tick)

def envelope_yaw(envelope):
    if envelope is None:raise ValueError('original_empirical_yaw_envelope_required')
    return float(envelope['rpy_abs_max'][2])+1e-9
