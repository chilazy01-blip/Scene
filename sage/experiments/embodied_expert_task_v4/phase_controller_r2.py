"""Continuous command trajectories and hysteresis around the prior geometric expert."""
import numpy as np
from sage.experiments.embodied_expert_task_v3.phase_controller_r10 import PhaseController as GeometricController
from sage.experiments.embodied_expert_task_v3.phase_reference_r2 import Progress as BaseProgress
from .command_trajectory_r2 import CommandTrajectory

class Progress(BaseProgress):
    def __init__(self,*args):super().__init__(*args);self.hold_label='retarget_not_feasible'
    def update(self,*args):
        result=super().update(*args)
        if self.hold_label!='retarget_not_feasible':result['reasons']=[self.hold_label if r=='retarget_not_feasible' else r for r in result['reasons']]
        return result

class PhaseController(GeometricController):
    def __init__(self,model,inputs,palm_reference,inspection,plan):
        super().__init__(model,inputs,palm_reference,inspection,plan);self.progress=Progress(plan,self.groups);self.motion=plan['command_trajectory'];self.trajectory=None;self.workspace_latched=False;self.workspace_ready=0;self.last_nav=np.zeros(3);self.indices=sorted(set(self.groups['upper_body'])-set(self.groups['lower_body']));hands=set(self.groups['left_hand']+self.groups['right_hand']);self.vmax=np.asarray([self.motion['hand_command_velocity_limit'] if j in hands else self.motion['arm_command_velocity_limit'] for j in self.indices]);self.amax=np.asarray([self.motion['hand_command_acceleration_limit'] if j in hands else self.motion['arm_command_acceleration_limit'] for j in self.indices])
    def targets(self,actual_q,advance=True):
        goal,requested,diag=super().targets(actual_q,advance=advance)
        if self.trajectory is None:self.trajectory=CommandTrajectory(np.clip(actual_q[self.inputs['qpos_by_pin']],self.inputs['native_lower_limits'],self.inputs['native_upper_limits']),self.indices,self.inputs['native_lower_limits'],self.inputs['native_upper_limits'],self.vmax,self.amax,self.plan['control_dt'])
        command,motion=self.trajectory.step(requested)
        if not diag['ik']['passed']:self.workspace_latched=True;self.workspace_ready=0
        elif self.workspace_latched:
            self.workspace_ready+=1
            if self.workspace_ready>=self.motion['workspace_ready_ticks']:self.workspace_latched=False
        pending=float(np.max(np.abs(command[self.indices]-requested[self.indices])))>.1
        core_hold=self.progress.external_hold
        self.progress.external_hold=core_hold or self.workspace_latched or pending
        self.progress.hold_label='retarget_not_feasible' if core_hold else 'command_transition_pending'
        nav_requested=np.asarray(goal['navigate_cmd']).copy();maximum=np.array([self.motion['navigation_xy_acceleration_per_axis']]*2+[self.motion['navigation_yaw_acceleration']])*self.plan['control_dt'];nav=self.last_nav+np.clip(nav_requested-self.last_nav,-maximum,maximum);self.last_nav=nav.copy();goal['navigate_cmd']=nav
        diag.update(command_trajectory=motion,command_transition_pending=pending,workspace_ready_ticks=self.workspace_ready,workspace_latched=self.workspace_latched,navigation_requested=nav_requested,navigation_applied=nav.copy(),goal=goal)
        return goal,command,diag
