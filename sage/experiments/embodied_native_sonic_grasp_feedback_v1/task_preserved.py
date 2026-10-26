"""Actual-contact six-dimensional allocation and persistent joint force feedback."""
import numpy as np
from .task_steady import Task as Previous
from .feedback import allocate,advance
from .relative_grip_wrench import wrench,limit_update
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.wrench_anchor=None;self.wrench_relative_rotation=None;self.wrench_minimums=None
    def force_update(self,tick,data,m):
        if tick<1362:return super().force_update(tick,data,m)
        h=hand_ids(self.model);pid=self.model.body('payload').id;R=data.xmat[self.wrist].reshape(3,3);cup_R=data.xmat[pid].reshape(3,3);cup=data.xipos[pid];mass=float(self.model.body_mass[pid]);weight=mass*abs(float(self.model.opt.gravity[2]));hv=np.zeros(6);cv=np.zeros(6);J=np.zeros((3,self.model.nv));Jr=J.copy();self.mujoco.mj_jac(self.model,data,J,Jr,data.xpos[self.wrist],self.wrist);hv[:3]=Jr@data.qvel;hv[3:]=J@data.qvel;self.mujoco.mj_jac(self.model,data,J,Jr,cup,pid);cv[:3]=Jr@data.qvel;cv[3:]=J@data.qvel
        if self.wrench_anchor is None:
            self.wrench_minimums={g:max(1.5,float(m['forces'][g])) for g in ('thumb','index','middle')};self.wrench_anchor=R.T@(cup-data.xpos[self.wrist]);self.wrench_relative_rotation=R.T@cup_R;self.events.append(dict(kind='loaded_actual_pose_force_control_anchor',tick=tick,preserved_minimum_normals_n=self.wrench_minimums.copy(),reference_com_wrist_m=self.wrench_anchor.tolist(),reference_cup_wrist_rotation=self.wrench_relative_rotation.tolist(),original_acceptance_slip_anchor_unchanged=True,physical_state_unchanged=True))
        target=wrench(weight,mass,data.xpos[self.wrist],R,self.wrench_anchor,self.wrench_relative_rotation,cup,cup_R,hv,cv);proposal=allocate(self.mujoco,self.model,data,self.wrench_minimums,target);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);ends=np.array([RIGHT_CLOSED[h['names'][i]]*.5 for i in ix]);old=self.finger_reference[ix].copy()
        if proposal['feasible']:
            assert proposal['right_finger_indices']==ix.tolist();candidate=advance(old,np.array(proposal['desired_contact_torque_nm']),np.array(proposal['measured_contact_torque_nm']),h['kp'][ix],np.minimum(0,ends),np.maximum(0,ends));self.finger_reference[ix]=limit_update(old,candidate,ends)
        else:
            for k,i in enumerate(ix):
                if m['forces'][group(h['names'][i])]<.15:self.finger_reference[i]+=np.clip(ends[k]-self.finger_reference[i],-.003,.003)
        self.feedback_allocation=proposal;assert np.max(np.abs(self.finger_reference[ix]-old))<=.006+1e-12
        if tick%5==0:self.events.append(dict(kind='native_relative_pose_wrench_joint_feedback',tick=tick,stage=self.stage,requested_contact_wrench=target.tolist(),allocation=proposal,persistent_right_joint_targets_rad=self.finger_reference[ix].tolist(),relative_velocity_damping=True,original_PD_effort_and_halfclosed_bounds=True,maximum_opening_step_rad=.001,maximum_any_step_rad=.006))
