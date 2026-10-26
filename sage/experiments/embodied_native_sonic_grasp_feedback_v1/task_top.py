"""Persistent finger impedance targets adjusted by measured contact force error."""
import numpy as np
from scipy.spatial.transform import Rotation
from .feedback import allocate,advance,ROLES
from .impedance import update as impedance_update
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.task import Task as Previous
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as BodyTask
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import evaluate
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_native_object_transport_v1.task_v3 import smooth

class ForceTask(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.impedance_anchor=None;self.integral_torque=None;self.friction_estimate=None;self.finger_reference=None;self.feedback_allocation=None;self.feedback_start=None;self.infeasible_ticks=0;self.com_anchor=None;self.cup_rotation=None;self.balance_origin=None;self.release_origin=None
    def move(self,tick,data,goal,rotation,duration=65):
        if tick>=790:duration={'tuck':60,'place':65,'retract':40}.get(self.stage,duration)
        return super().move(tick,data,goal,rotation,duration)
    def force_update(self,tick,data,m):
        h=hand_ids(self.model);pid=self.model.body('payload').id;mass=self.model.body_mass[pid];weight=mass*abs(self.model.opt.gravity[2]);com=data.xipos[pid];R=data.xmat[self.wrist].reshape(3,3)
        velocity=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,pid,velocity,0)
        if self.stage=='force_balance':desired_com=self.balance_origin;fraction=0.
        else:desired_com=data.xpos[self.wrist]+R@self.com_anchor;fraction=1.
        stiffness=weight/.025;damping=2*np.sqrt(stiffness*mass);force=stiffness*(desired_com-com)-damping*velocity[3:]+np.array([0,0,fraction*weight]);force[:2]=np.clip(force[:2],-.5*weight,.5*weight);force[2]=np.clip(force[2],0,2*weight)
        rerror=Rotation.from_matrix(self.cup_rotation@data.xmat[pid].reshape(3,3).T).as_rotvec();torque=np.clip(.05*rerror-.01*velocity[:3],-.02,.02)
        proposal=allocate(self.mujoco,self.model,data,self.preload_targets,np.r_[force,torque]);self.feedback_allocation=proposal
        if proposal['feasible']:
            ix=np.array(proposal['right_finger_indices']);end=np.array([RIGHT_CLOSED[h['names'][i]]*.5 for i in ix]);
            if self.impedance_anchor is None:
                self.impedance_anchor=data.qpos[h['qpos'][ix]].copy();self.integral_torque=np.zeros(len(ix));self.friction_estimate=np.array(proposal['native_joint_friction_nm'])
            target,self.integral_torque,self.friction_estimate,meta=impedance_update(self.finger_reference[ix],self.impedance_anchor,self.integral_torque,self.friction_estimate,np.array(proposal['desired_contact_torque_nm']),np.array(proposal['measured_contact_torque_nm']),np.array(proposal['bias_nm']),np.array(proposal['native_joint_friction_nm']),h['kp'][ix],np.minimum(0,end),np.maximum(0,end))
            self.finger_reference[ix]=target;proposal['anchored_impedance']=meta;proposal['fixed_anchor_rad']=self.impedance_anchor.tolist();self.infeasible_ticks=0
        else:
            self.infeasible_ticks+=1
            # Only unloaded finger groups reacquire; loaded targets hold their impedance.
            for i,n in enumerate(h['names']):
                if n not in RIGHT_CLOSED:continue
                from sage.experiments.embodied_carry_v1.grasp import group
                if m['forces'][group(n)]<.15:
                    end=RIGHT_CLOSED[n]*.5;self.finger_reference[i]+=np.clip(end-self.finger_reference[i],-.003,.003)
        if tick%5==0:self.events.append(dict(kind='measured_contact_force_admittance',tick=tick,stage=self.stage,allocation=proposal,persistent_hand_targets_rad=self.finger_reference.tolist(),effective_position_and_velocity_feedback_preserved=True))
    def recover(self,tick,data,m,reason):
        self.recovery_reason=reason;self.failure=reason;self.events.append(dict(kind='failed_load_trial_stopped',tick=tick,reason=reason))
    def update(self,tick,data,m):
        if tick<790:return super().update(tick,data,m)
        if self.done or self.failure:return
        self.last_object_local=m['object_local_m'];pid=self.model.body('payload').id;h=hand_ids(self.model)
        if self.feedback_start is None:
            self.finger_reference=np.array(super().hand_targets(h['names']));self.feedback_start=tick;self.balance_origin=data.xipos[pid].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(self.balance_origin-data.xpos[self.wrist]);self.cup_rotation=data.xmat[pid].reshape(3,3).copy();self.change('force_balance',tick,data,m)
        age=tick-self.start
        if tick%5==0 or self.quality is None:
            self.quality=evaluate(self.mujoco,self.model,data);self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=self.quality,group_closures=None))
        q=self.quality
        if self.stage not in ('release','retract','settle','done'):self.force_update(tick,data,m)
        if self.stage=='force_balance':
            if np.linalg.norm(np.array(m['object_m'])[:2]-np.array(self.case['source_object_xyz_m'])[:2])>.04:self.failure='grasp_pushed_object';return
            if age>200:self.failure='realized_wrench_balance_timeout';return
            ready=q['qualified'] and q['hand_force_world_n'][2]>=-.5*q['weight_n'] and np.linalg.norm(q['hand_force_world_n'][:2])<=.5*q['weight_n'] and np.linalg.norm(q['hand_torque_nm'])<=.02 and self.reached(tick,data)
            self.stable=self.stable+1 if ready else 0
            if self.stable>=15:
                self.anchor=np.array(m['object_local_m']);self.probe_origin=np.array(m['object_m']);self.probe_wrist=data.xpos[self.wrist].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(data.xipos[pid]-self.probe_wrist)
                self.change('load_probe',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.01],self.grasp_R,60)
        elif self.stage=='load_probe':
            slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
            if slip>.008:self.recover(tick,data,m,'probe_relative_slip');return
            if age>=70:
                ready=m['object_m'][2]-self.probe_origin[2]>=.006 and not m['desk_supported'] and q['hand_force_world_n'][2]>=.8*q['weight_n'] and q['qualified'] and slip<=.006
                if not ready:self.recover(tick,data,m,'probe_load_not_transferred');return
                self.probe_passed=True;self.change('lift',tick,data,m);self.move(tick,data,self.probe_wrist+[0,0,.05],self.grasp_R,60)
        elif self.stage in ('lift','loaded_hover'):
            slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
            if slip>.015:self.recover(tick,data,m,'loaded_relative_slip');return
            ready=not m['desk_supported'] and m['object_bottom_m']>self.case['support_top_m']+.025 and q['qualified'] and q['hand_force_world_n'][2]>=.8*q['weight_n']
            if self.stage=='lift':
                if age>150:self.recover(tick,data,m,'real_lift_not_qualified');return
                if self.reached(tick,data) and ready:self.change('loaded_hover',tick,data,m)
            else:
                self.stable=self.stable+1 if ready else 0
                if age>120:self.recover(tick,data,m,'loaded_hover_unstable');return
                if self.stable>=50:
                    self.grasp_test_passed=True;self.events.append(dict(kind='loaded_hover_passed',tick=tick,time_s=float(data.time)));self.object_lift_origin=np.array(m['object_m']);self.change('tuck',tick,data,m);self.move(tick,data,data.qpos[:3]+np.array(self.case['ready_arm_relative_m']),self.grasp_R,60)
        elif self.stage=='release':
            if self.release_origin is None:self.release_origin=self.finger_reference.copy()
            self.finger_reference=self.release_origin*(1-float(smooth(age/60)));self.closure=self.case['grip_closure']*(1-float(smooth(age/60)))
            if age>=70 and m['desk_supported']:self.change('retract',tick,data,m);self.move(tick,data,data.xpos[self.wrist]+[-.15,0,.08],self.grasp_R,40)
        else:
            BodyTask.update(self,tick,data,m)
            if self.stage in ('retract','settle','done'):self.finger_reference[:]=0.
    def hand_targets(self,names):
        if self.finger_reference is not None:return self.finger_reference.tolist()
        return super().hand_targets(names)

from .wrist_damping import DampedReference
from sage.experiments.embodied_carry_v1.grasp import group
class Task(ForceTask):
    """Axis/aperture-derived vertical grasp reference; SONIC owns all body actions."""
    def synchronize(self,tick,data,force=False):
        if tick>=790 and self.path is not None:
            if not isinstance(self.feedback,DampedReference):self.feedback=DampedReference(self.feedback)
            vel=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.wrist,vel,0)
            pos,R=self.desired(tick);pn,Rn=self.desired(tick+1)
            self.feedback.velocity=vel[3:]-(pn-pos)/.02
            self.feedback.angular_velocity=vel[:3]-Rotation.from_matrix(Rn@R.T).as_rotvec()/.02
        return BodyTask.synchronize(self,tick,data,force)
    def move(self,tick,data,goal,rotation,duration=65):
        if tick>=790:
            rotation=self.grasp_R
            grasp=np.array(self.last_object_local_world)-np.array(self.case['grasp_local_xyz_m'])
            if self.stage in ('preinsert','lower','insert'):
                goal=grasp+np.array([0,0,{'preinsert':.10,'lower':.05,'insert':0.}[self.stage]])
                duration={'preinsert':90,'lower':50,'insert':50}[self.stage]
            if self.stage=='tuck':
                goal=np.array(goal);goal[2]=max(goal[2],data.xpos[self.wrist,2])
        return super().move(tick,data,goal,rotation,duration)
    def update(self,tick,data,m):
        self.last_object_local_world=np.array(m['object_m'])
        if tick<790:return BodyTask.update(self,tick,data,m)
        if self.done or self.failure:return
        if self.stage in ('ready_arm','preinsert','lower','insert'):
            return BodyTask.update(self,tick,data,m)
        if self.stage=='close':
            self.last_object_local=m['object_local_m'];h=hand_ids(self.model)
            if self.finger_reference is None:
                self.finger_reference=np.zeros(len(h['names']));self.group_values={g:0. for g in ROLES}
            if tick-self.start>200:self.failure='top_three_finger_preload_timeout';return
            if np.linalg.norm(np.array(m['object_m'])[:2]-self.case['source_object_xyz_m'][:2])>.04:self.failure='grasp_pushed_object';return
            for i,n in enumerate(h['names']):
                if n not in RIGHT_CLOSED:continue
                g=group(n)
                if m['forces'][g]<self.preload_targets[g]:
                    target=RIGHT_CLOSED[n]*min(.5,self.case['top_nominal_closure']+.05)
                    self.finger_reference[i]+=np.clip(target-self.finger_reference[i],-.006,.006)
            for g in ROLES:
                self.group_values[g]=max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.)
            self.closure=max(self.group_values.values())
            self.quality=evaluate(self.mujoco,self.model,data)
            if tick%5==0:self.events.append(dict(kind='top_actual_preload',tick=tick,stage=self.stage,forces=dict(m['forces']),quality=self.quality,group_closures=self.group_values.copy()))
            ready=self.reached(tick,data) and all(m['forces'][g]>=min(.15,self.preload_targets[g]) for g in ROLES)
            self.stable=self.stable+1 if ready else 0
            if self.stable>=5:
                pid=self.model.body('payload').id;self.feedback_start=tick;self.balance_origin=data.xipos[pid].copy();self.com_anchor=data.xmat[self.wrist].reshape(3,3).T@(self.balance_origin-data.xpos[self.wrist]);self.cup_rotation=data.xmat[pid].reshape(3,3).copy();self.change('force_balance',tick,data,m)
            return
        return super().update(tick,data,m)
