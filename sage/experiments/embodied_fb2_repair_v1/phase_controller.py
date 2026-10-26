"""Prepared integration of the repair layers; physical task admission is external.

This controller requires measured q AND dq. Geometry checks are necessary but
never reported as proof of dynamic braking, grasping or full-task success.
"""
import numpy as np
from sage.experiments.embodied_expert_task_v5.geometric_controller import BasePhaseController
from sage.experiments.embodied_expert_task_v3.phase_reference_r2 import interpolate,reference_qpos,yaw,angle_difference
from .ik_r2 import UpperTargetSolver
from .geometry import ClearanceGuard
from .proximity import TableApproachGuard
from .motion_r2 import MotionGovernor


class PhaseController(BasePhaseController):
    def __init__(self,model,inputs,palm_reference,inspection,plan):
        super().__init__(model,inputs,palm_reference,inspection,plan)
        self.solver=UpperTargetSolver(model,inputs['qpos_by_pin'],self.groups,plan)
        self.clearance=ClearanceGuard(model,plan['forbidden_target_gap_m'],plan['target_hand_penetration_m'])
        self.approach=TableApproachGuard(model);self.governor=None;self.root_stop=None;self.last_nav=np.zeros(3)
        self.indices=np.array(sorted(set(self.groups['upper_body'])-set(self.groups['lower_body'])))
        motion=plan['command_trajectory'];hands=self.groups['left_hand']+self.groups['right_hand']
        self.vmax=np.array([motion['hand_command_velocity_limit'] if k in hands else motion['arm_command_velocity_limit'] for k in self.indices])
        self.amax=np.array([motion['hand_command_acceleration_limit'] if k in hands else motion['arm_command_acceleration_limit'] for k in self.indices])

    def targets(self,actual_q,actual_v,advance=True):
        q=np.asarray(actual_q);v=np.asarray(actual_v)
        if q.shape!=(57,) or v.shape!=(55,) or not np.isfinite(q).all() or not np.isfinite(v).all():
            raise ValueError('actual_full_state_and_velocity_required')
        mapping=self.inputs['qpos_by_pin'];pin=q[mapping];velocity=v[mapping-1]
        if self.governor is None:
            initial=np.clip(pin,self.inputs['native_lower_limits'],self.inputs['native_upper_limits'])
            self.governor=MotionGovernor(initial,self.indices,self.inputs['native_lower_limits'],self.inputs['native_upper_limits'],self.vmax,self.amax,self.ratio[self.indices],self.plan['control_dt'])
        safety=self.approach.evaluate(q,v);p=self.progress;old_phase=p.phase
        p.external_hold=self.governor.mode!='track' or not safety['safe_to_approach']
        goal,requested,diag=super().targets(q,advance=advance)
        command,motion=self.governor.step(pin,velocity,requested,diag['ik']['passed'],safety,allow_resume=advance)
        if not motion['phase_advance_allowed']:
            p.phase=old_phase
            if advance and p.hold_seconds==0:p.hold_seconds=self.plan['control_dt']
            p.external_hold=True
            if motion['entry']:self.root_stop=q[:7].copy()
            p.last_target=command.copy();p.last_target[self.indices]=motion['fixed_anchor']
        else:self.root_stop=None
        phase=p.phase;reference=reference_qpos(self.inputs,phase)
        ff=interpolate(self.inputs['navigate'],min(phase,920.))*self.plan['phase_rate']
        theta=yaw(q[3:7]);ref_theta=yaw(reference[3:7]);R=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]);Rref=np.array([[np.cos(ref_theta),-np.sin(ref_theta)],[np.sin(ref_theta),np.cos(ref_theta)]])
        root_target=reference[:2]
        if not motion['phase_advance_allowed'] or not advance:
            ff=np.zeros(3)
            if self.root_stop is not None:root_target=self.root_stop[:2];ref_theta=yaw(self.root_stop[3:7])
        world_ff=Rref@ff[:2]
        desired=np.zeros(3);desired[:2]=R.T@(world_ff+2*(root_target-q[:2])-.5*(v[:2]-world_ff))
        desired[2]=ff[2]+angle_difference(ref_theta,theta)-.2*(v[5]-ff[2])
        desired=np.clip(desired,[-.25,-.25,-.35],[.25,.25,.35]);max_change=np.array([.3,.3,.5])*self.plan['control_dt'];nav=self.last_nav+np.clip(desired-self.last_nav,-max_change,max_change);self.last_nav=nav.copy()
        # Waist columns carry source torso orientation INTENT, not measured waist angles.
        native_upper=interpolate(self.inputs['upper'],min(phase,920.)).copy()
        for column,index in enumerate(self.groups['upper_body']):
            if index in self.indices:native_upper[column]=command[index]
        goal.update(navigate_cmd=nav,base_height_command=interpolate(self.inputs['height'],min(phase,920.)),wrist_pose=interpolate(self.inputs['wrist'],min(phase,920.)),target_upper_body_pose=native_upper)
        geometry=self.clearance.check_path(q,command,mapping,self.indices,samples=9)
        reasons=diag['progress']['reasons'][:]
        if not motion['phase_advance_allowed']:reasons.append('measured_velocity_brake_or_hold')
        if p.hold_seconds>self.plan['max_hold_seconds']:reasons.append('progress_timeout')
        diag.update(phase=phase,goal=goal,motion=motion,safety=safety,command_clearance=geometry,control_target_passed=geometry['passed'],control_mode=motion['mode'],physical_braking_certified=False,root_reference=reference[:3].copy(),root_control_target=root_target.copy())
        diag['progress'].update(phase=phase,hold_seconds=p.hold_seconds,reasons=sorted(set(reasons)))
        return goal,command,diag
