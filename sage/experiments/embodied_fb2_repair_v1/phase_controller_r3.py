"""Coordinated-path integration; offline until independent physical admission.

Task targets never become stop anchors. Native lower-body/torso goal semantics
are retained; upper commands come exclusively from the checked path planner.
"""
import numpy as np
from sage.experiments.embodied_expert_task_v5.geometric_controller import BasePhaseController
from sage.experiments.embodied_expert_task_v3.phase_reference_r2 import interpolate,reference_qpos,yaw,angle_difference
from .ik_r2 import UpperTargetSolver
from .proximity import TableApproachGuard
from .coordinated_geometry_r1 import ProspectiveClearance
from .coordinated_motion_r1 import CoordinatedGovernor


class PhaseController(BasePhaseController):
    def __init__(self,model,inputs,palm_reference,inspection,plan,deadline=lambda:None):
        super().__init__(model,inputs,palm_reference,inspection,plan)
        self.solver=UpperTargetSolver(model,inputs['qpos_by_pin'],self.groups,plan)
        self.indices=np.array(sorted(set(self.groups['upper_body'])-set(self.groups['lower_body'])))
        motion=plan['command_trajectory'];hands=self.groups['left_hand']+self.groups['right_hand']
        self.vmax=np.array([motion['hand_command_velocity_limit'] if i in hands else motion['arm_command_velocity_limit'] for i in self.indices])
        self.amax=np.array([motion['hand_command_acceleration_limit'] if i in hands else motion['arm_command_acceleration_limit'] for i in self.indices])
        self.clearance=ProspectiveClearance(model,inputs['qpos_by_pin'],self.indices,plan['forbidden_target_gap_m'],plan['target_hand_penetration_m'])
        self.approach=TableApproachGuard(model);self.governor=None;self.root_stop=None;self.last_nav=np.zeros(3);self.deadline=deadline;self.failed=False

    def targets(self,actual_q,actual_v,advance=True):
        if self.failed:raise RuntimeError('coordinated_controller_failed_closed')
        q=np.asarray(actual_q);v=np.asarray(actual_v)
        if q.shape!=(57,) or v.shape!=(55,) or not np.isfinite(q).all() or not np.isfinite(v).all():raise ValueError('actual_full_state_and_velocity_required')
        mapping=self.inputs['qpos_by_pin'];pin=q[mapping];velocity=v[mapping-1]
        if self.governor is None:
            initial=pin.copy();lo=self.inputs['native_lower_limits'];hi=self.inputs['native_upper_limits'];excess=np.maximum(lo-initial,initial-hi);outside=excess[self.indices]>0
            if np.any(excess[self.indices][outside]>1e-4) or np.any(abs(velocity[self.indices][outside])>.005):raise ValueError('initial_command_projection_not_quasistatic')
            initial[self.indices]=np.clip(initial[self.indices],lo[self.indices],hi[self.indices])
            self.governor=CoordinatedGovernor(initial,self.indices,lo,hi,self.vmax,self.amax,self.plan['control_dt'],self.groups['left_arm']+self.groups['right_arm'])
        safety=self.approach.evaluate(q,v);p=self.progress;old_phase=p.phase
        old_task_target=None if p.last_target is None else p.last_target.copy()
        previous=None if self.previous_target is None else self.previous_target.copy()
        old_anchor=None if p.anchor is None else p.anchor.copy()
        solver_last=None if self.solver.last is None else self.solver.last.copy()
        p.external_hold=self.governor.mode!='track' or self.governor.rejoin_required or not self.governor.task_route_admitted or not safety['safe_to_approach']
        goal,_,diag=super().targets(q,advance=advance)
        # FF is included before coordinated planning; no clipping/trim follows it.
        requested=np.array(diag['target']);requested[self.indices]+=self.ratio[self.indices]*np.asarray(diag['feedforward_velocity'])[self.indices]
        validate=self.clearance.bind(q,v,self.deadline)
        waypoints=lambda:self._pregrasp_waypoints(q,diag['target'],p.phase)
        try:
            command,motion=self.governor.step(pin,velocity,requested,diag['target'],diag['ik']['passed'],safety,validate,allow_resume=advance,waypoints=waypoints if p.phase<self.plan['grasp_end_phase'] else (),tracking_tolerance=min(self.plan['arm_advance_tolerance_rad'],self.plan['hand_advance_tolerance_rad']))
        except BaseException:
            p.phase=old_phase;p.anchor=old_anchor;p.last_target=old_task_target;p.external_hold=True
            self.previous_target=previous;self.solver.last=solver_last;self.failed=True
            raise
        if not motion['phase_advance_allowed']:
            if p.phase!=old_phase:
                p.phase=old_phase;p.anchor=old_anchor;self.previous_target=previous;self.solver.last=solver_last
                goal,_,fixed=super().targets(q,advance=False)
                # Transactional phase rollback also restores its IK task target.
                fixed['progress']=diag['progress'];diag=fixed
            if advance and p.hold_seconds==0:p.hold_seconds=self.plan['control_dt']
            p.external_hold=True
            if motion['entry']:self.root_stop=q[:7].copy()
        else:self.root_stop=None
        # p.last_target remains the task IK solution set by BasePhaseController.
        phase=p.phase;reference=reference_qpos(self.inputs,phase)
        ff=interpolate(self.inputs['navigate'],min(phase,920.))*self.plan['phase_rate']
        theta=yaw(q[3:7]);ref_theta=yaw(reference[3:7]);R=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]);Rref=np.array([[np.cos(ref_theta),-np.sin(ref_theta)],[np.sin(ref_theta),np.cos(ref_theta)]])
        root_target=reference[:2]
        if not motion['phase_advance_allowed'] or not advance:
            ff=np.zeros(3)
            if self.root_stop is not None:root_target=self.root_stop[:2];ref_theta=yaw(self.root_stop[3:7])
        world_ff=Rref@ff[:2];desired=np.zeros(3)
        desired[:2]=R.T@(world_ff+2*(root_target-q[:2])-.5*(v[:2]-world_ff));desired[2]=ff[2]+angle_difference(ref_theta,theta)-.2*(v[5]-ff[2])
        desired=np.clip(desired,[-.25,-.25,-.35],[.25,.25,.35]);max_change=np.array([.3,.3,.5])*self.plan['control_dt'];nav=self.last_nav+np.clip(desired-self.last_nav,-max_change,max_change);self.last_nav=nav.copy()
        native_upper=interpolate(self.inputs['upper'],min(phase,920.)).copy()
        for column,index in enumerate(self.groups['upper_body']):
            if index in self.indices:native_upper[column]=command[index]
        goal.update(navigate_cmd=nav,base_height_command=interpolate(self.inputs['height'],min(phase,920.)),wrist_pose=interpolate(self.inputs['wrist'],min(phase,920.)),target_upper_body_pose=native_upper)
        final=q.copy();final[mapping[self.indices]]=command[self.indices];geometry=self.clearance.check(final)
        reasons=diag['progress']['reasons'][:]
        if not motion['phase_advance_allowed']:reasons.append('coordinated_brake_hold_or_task_rejoin')
        if p.hold_seconds>self.plan['max_hold_seconds']:reasons.append('progress_timeout')
        diag.update(phase=phase,goal=goal,motion=motion,safety=safety,command_clearance=geometry,control_target_passed=geometry['passed'],control_mode=motion['mode'],physical_braking_certified=False,root_reference=reference[:3].copy(),root_control_target=root_target.copy(),task_target_distinct_from_stop_anchor=True)
        diag['progress'].update(phase=phase,hold_seconds=p.hold_seconds,reasons=sorted(set(reasons)))
        return goal,command,diag

    def _pregrasp_waypoints(self,actual,task_target,phase):
        # Bounded route alternatives, generated only after direct/slower paths fail.
        # Hand closure is held at its measured posture while making clearance.
        import mujoco
        mapping=self.inputs['qpos_by_pin']
        posture=reference_qpos(self.inputs,phase)[mapping].copy()
        hand=self.groups['left_hand']+self.groups['right_hand']
        posture[hand]=actual[mapping[hand]]
        yield posture
        saved=None if self.solver.last is None else self.solver.last.copy()
        data=self.solver.data;data.qpos[:]=actual;data.qvel[:]=0
        mujoco.mj_fwdPosition(self.solver.model,data)
        positions=np.array([data.xpos[b].copy() for b in self.solver.palms])
        rotations=np.array([data.xmat[b].reshape(3,3).copy() for b in self.solver.palms])
        seed=np.asarray(task_target).copy();seed[hand]=actual[mapping[hand]]
        try:
            for height in [.015,.03]:
                self.deadline();raised=positions.copy();raised[:,2]+=height
                candidate,diagnosis=self.solver.solve(actual,seed,raised,rotations)
                if diagnosis['passed']:yield candidate
        finally:
            self.solver.last=saved

    def combine(self,native_action,upper_command):
        # Preserve native lower-body behavior. No independent upper clipping.
        action=super().combine(native_action,upper_command)
        if not np.allclose(action['q'][self.indices],np.asarray(upper_command)[self.indices],rtol=0,atol=1e-10):raise RuntimeError('post_planner_upper_command_modified')
        action['q'][self.indices]=np.asarray(upper_command)[self.indices]
        return action
