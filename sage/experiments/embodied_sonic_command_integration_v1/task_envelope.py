"""Preserved loaded preload and actual6D contact torques, with original native hand PD."""
import numpy as np
from .task_fast import Task as Previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.feedback import advance
from .native_envelope import allocate
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.relative_grip_wrench import wrench
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

def fast_update(old,desired,measured,kp,ends):
    ends=np.asarray(ends)
    candidate=advance(old,desired,measured,kp,np.minimum(0,ends),np.maximum(0,ends),gain=10.)
    return np.clip(np.asarray(old)+np.clip(candidate-old,-.006,.006),np.minimum(0,ends),np.maximum(0,ends))

def extension_ready(task,tick):
    return getattr(task,'native_envelope_enabled',False) or (task.stage=='carry' and task.walk_start is not None and tick-task.walk_start>=40)

class Task(Previous):
    def force_update(self,tick,data,m):
        if not extension_ready(self,tick):return super().force_update(tick,data,m)
        if not getattr(self,'native_envelope_enabled',False):
            self.native_envelope_enabled=True
            self.events.append(dict(kind='native_loaded_reference_envelope_extended',tick=tick,old_ratio=.5,new_ratio=self.case['loaded_native_reference_ratio'],original_model_joint_ranges_PD_effort_friction_unchanged=True,different_control_regime_from_halfclosed_baseline=True))
        ratio=float(self.case['loaded_native_reference_ratio'])
        if not self.grasp_test_passed:return super().force_update(tick,data,m)
        # During intentional table placement retain the acquired grip without
        # commanding a new upward support wrench; original release is unchanged.
        if self.stage=='place':return
        if self.stage not in ('tuck','carry','target_stop'):return super().force_update(tick,data,m)
        h=hand_ids(self.model);pid=self.model.body('payload').id;R=data.xmat[self.wrist].reshape(3,3);cupR=data.xmat[pid].reshape(3,3);cup=data.xipos[pid];mass=float(self.model.body_mass[pid]);weight=mass*abs(float(self.model.opt.gravity[2]))
        hv=np.zeros(6);cv=np.zeros(6);J=np.zeros((3,self.model.nv));Jr=J.copy()
        self.mujoco.mj_jac(self.model,data,J,Jr,data.xpos[self.wrist],self.wrist);hv[:3]=Jr@data.qvel;hv[3:]=J@data.qvel
        self.mujoco.mj_jac(self.model,data,J,Jr,cup,pid);cv[:3]=Jr@data.qvel;cv[3:]=J@data.qvel
        if not hasattr(self,'contact_pose_anchor'):
            self.contact_pose_anchor=R.T@(cup-data.xpos[self.wrist]);self.contact_relative_R=R.T@cupR
            self.contact_minimum={g:max(float(self.tracking_goals[g]),float(m['forces'][g])) for g in ('thumb','index','middle')}
            self.events.append(dict(kind='preserved_loaded_contact_torque_tracking_enabled',tick=tick,minimum_normals_n=self.contact_minimum.copy(),controller_pose_anchor_m=self.contact_pose_anchor.tolist(),original_acceptance_slip_anchor_unchanged=True))
        target=wrench(weight,mass,data.xpos[self.wrist],R,self.contact_pose_anchor,self.contact_relative_R,cup,cupR,hv,cv)
        proposal=allocate(self.mujoco,self.model,data,self.contact_minimum,target,ratio);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);ends=np.array([RIGHT_CLOSED[h['names'][i]]*ratio for i in ix]);old=self.finger_reference[ix].copy()
        if proposal['feasible']:
            assert proposal['right_finger_indices']==ix.tolist()
            self.finger_reference[ix]=fast_update(old,np.asarray(proposal['desired_contact_torque_nm']),np.asarray(proposal['measured_contact_torque_nm']),h['kp'][ix],ends)
        self.feedback_allocation=proposal
        self.group_values={g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in ('thumb','index','middle')};self.closure=max(self.group_values.values())
        assert np.max(np.abs(self.finger_reference[ix]-old))<=.006+1e-12
        if tick%5==0:self.events.append(dict(kind='preserved_loaded_native_contact_torque_feedback',tick=tick,stage=self.stage,requested_wrench=target.tolist(),allocation=proposal,reference_rad=self.finger_reference.tolist(),maximum_opening_delta_rad=.006,reference_contact_error_gain_per_s=10.,infeasible_action='hold_previous_native_references',native_PD_effort_friction_and_task_gates_unchanged=True))
