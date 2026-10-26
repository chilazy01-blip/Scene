"""Move the opposing grasp onto the cup body and reject an edge-loaded drifting grip."""
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_sonic_command_integration_v1.task_envelope import Task as Previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path
from sage.experiments.embodied_native_sonic_loaded_grasp_v1.quality import evaluate
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.relative_grip_wrench import wrench
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.feedback import advance
from .allocator import allocate
from sage.experiments.embodied_sonic_command_integration_v1.wrist_smooth import SmoothReference
from sage.experiments.embodied_native_sonic_transport_v1.task_ordered import Task as BodyTask


class Task(Previous):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.body_realign_started=None;self.body_realign_done=False;self.body_hover_history=[]
        h=hand_ids(self.model)
        self.body_motor_goal=np.array([self.case['body_motor_reference_rad'].get(n,0.) for n in h['names']])

    def synchronize(self,tick,data,force=False):
        if self.stage!='body_realign':return super().synchronize(tick,data,force)
        if not isinstance(self.feedback,SmoothReference):self.feedback=SmoothReference(self.feedback)
        velocity=np.zeros(6);self.mujoco.mj_objectVelocity(self.model,data,self.mujoco.mjtObj.mjOBJ_BODY,self.wrist,velocity,0)
        p,R=self.desired(tick);pn,Rn=self.desired(tick+1)
        self.feedback.velocity=velocity[3:]-(pn-p)/.02
        self.feedback.angular_velocity=velocity[:3]-Rotation.from_matrix(Rn@R.T).as_rotvec()/.02
        return BodyTask.synchronize(self,tick,data,force=True)

    def normal_control(self,tick,data,m):
        if tick<980:return super().normal_control(tick,data,m)
        self.equilibrium_motor_goal=self.body_motor_goal
        if self.loaded_balance_started is None:return super().normal_control(tick,data,m)
        roles=('thumb','index','middle');h=hand_ids(self.model);ratio=self.case['loaded_native_reference_ratio']
        if not hasattr(self,'tracking_goals'):
            self.tracking_goals={g:max(float(self.normal_targets[g]),float(m['forces'][g])) for g in roles}
            self.tracking_filtered={g:float(m['forces'][g]) for g in roles}
            self.events.append(dict(kind='native_loaded_preload_tracking_enabled',tick=tick,targets_n=self.tracking_goals.copy(),source='actual_body_grasp_load_transfer',native_model_PD_effort_unchanged=True))
        alpha=1-np.exp(-.02/.05)
        for g in roles:self.tracking_filtered[g]+=alpha*(m['forces'][g]-self.tracking_filtered[g])
        for i,n in enumerate(h['names']):
            if n not in RIGHT_CLOSED:continue
            g=group(n);deficit=max(0.,self.tracking_goals[g]-self.tracking_filtered[g]);delta=np.sign(RIGHT_CLOSED[n])*min(.006,.02*.2*deficit)
            end=RIGHT_CLOSED[n]*ratio;native=self.model.joint(n).range
            self.finger_reference[i]=np.clip(self.finger_reference[i]+delta,max(min(0,end),native[0]),min(max(0,end),native[1]))
        self.group_values={g:max([abs(self.finger_reference[i]/RIGHT_CLOSED[n]) for i,n in enumerate(h['names']) if n in RIGHT_CLOSED and group(n)==g],default=0.) for g in roles};self.closure=max(self.group_values.values())

    def force_update(self,tick,data,m):
        if not self.grasp_test_passed:return super().force_update(tick,data,m)
        if self.stage=='place':return
        if self.stage not in ('tuck','carry','target_stop'):return super().force_update(tick,data,m)
        h=hand_ids(self.model);pid=self.model.body('payload').id;R=data.xmat[self.wrist].reshape(3,3);cupR=data.xmat[pid].reshape(3,3);cup=data.xipos[pid]
        mass=float(self.model.body_mass[pid]);weight=mass*abs(float(self.model.opt.gravity[2]));hv=np.zeros(6);cv=np.zeros(6);J=np.zeros((3,self.model.nv));Jr=J.copy()
        self.mujoco.mj_jac(self.model,data,J,Jr,data.xpos[self.wrist],self.wrist);hv[:3]=Jr@data.qvel;hv[3:]=J@data.qvel
        self.mujoco.mj_jac(self.model,data,J,Jr,cup,pid);cv[:3]=Jr@data.qvel;cv[3:]=J@data.qvel
        if not hasattr(self,'contact_pose_anchor'):
            self.contact_pose_anchor=R.T@(cup-data.xpos[self.wrist]);self.contact_relative_R=R.T@cupR
            self.contact_minimum={g:max(float(self.tracking_goals[g]),float(m['forces'][g])) for g in ('thumb','index','middle')}
        target=wrench(weight,mass,data.xpos[self.wrist],R,self.contact_pose_anchor,self.contact_relative_R,cup,cupR,hv,cv)
        ratio=self.case['loaded_native_reference_ratio'];proposal=allocate(self.mujoco,self.model,data,self.contact_minimum,target,ratio)
        ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);ends=np.array([RIGHT_CLOSED[h['names'][i]]*ratio for i in ix]);old=self.finger_reference[ix].copy()
        if proposal['feasible']:self.finger_reference[ix]=advance(old,np.array(proposal['desired_contact_torque_nm']),np.array(proposal['measured_contact_torque_nm']),h['kp'][ix],np.minimum(0,ends),np.maximum(0,ends),gain=10.)
        self.feedback_allocation=proposal
        if tick%5==0:self.events.append(dict(kind='body_grasp_native_wrench_feedback',tick=tick,stage=self.stage,requested_wrench=target.tolist(),allocation=proposal,reference_rad=self.finger_reference.tolist(),reference_ratio=ratio,native_physics_unchanged=True))

    def contact_margin(self,data):
        pid=self.model.body('payload').id;R=data.xmat[pid].reshape(3,3);origin=data.xpos[pid];top=float(np.max(self.case['mug_local_bounds_corners'],axis=0)[2])
        points={g:[] for g in ['thumb','index','middle']}
        for i,c in enumerate(data.contact):
            pair=contact_pair(self.model,c);names=[x['name'] for x in pair]
            if 'payload_surface' not in names:continue
            other=pair[1-names.index('payload_surface')];g=group(other['body'])
            if g not in points:continue
            f=np.zeros(6);self.mujoco.mj_contactForce(self.model,data,i,f)
            if f[0]>.01:points[g].append((float(f[0]),float(((c.pos-origin)@R)[2])))
        return {g:top-float(np.average([x[1] for x in v],weights=[x[0] for x in v])) if v else -1. for g,v in points.items()}

    def update(self,tick,data,m):
        if tick<980:return super().update(tick,data,m)
        if self.done or self.failure:return
        if not self.body_realign_done:
            if self.body_realign_started is None:
                self.body_realign_started=tick
                p,R=self.desired(tick);self.grasp_R=np.array(self.case['body_grasp_rotation'])
                goal=np.array(self.case['body_grasp_wrist_goal_m'])
                self.change('body_realign',tick,data,m)
                self.path=make_path(tick,p,R,goal,self.grasp_R,90);self.joint_path=None
                self.events.append(dict(kind='body_contact_realign',tick=tick,origin=p.tolist(),goal=goal.tolist(),rotation=self.grasp_R.tolist(),duration=90,no_finger_closure_until_realigned=True))
            self.finger_reference=np.zeros(14);self.closure=0.
            if tick-self.body_realign_started>200:self.failure='body_realign_tracking_timeout';return
            if np.linalg.norm(np.array(m['object_m'])[:2]-self.case['source_object_xyz_m'][:2])>.04:self.failure='body_realign_pushed_object';return
            if self.reached(tick,data):
                self.body_realign_done=True;self.change('close',tick,data,m)
            return
        if self.stage!='loaded_hover':return super().update(tick,data,m)
        self.last_object_local=m['object_local_m'];self.last_object_local_world=np.array(m['object_m'])
        self.force_update(tick,data,m)
        q=evaluate(self.mujoco,self.model,data);self.quality=q
        if tick%5==0:self.events.append(dict(kind='actual_wrench_quality',tick=tick,stage=self.stage,quality=q,group_closures=None))
        slip=float(np.linalg.norm(np.array(m['object_local_m'])-self.anchor));self.max_slip=max(self.max_slip,slip)
        if slip>.015:self.failure='loaded_relative_slip';return
        margins=self.contact_margin(data)
        self.body_hover_history.append((tick,np.array(m['object_local_m'])))
        self.body_hover_history=self.body_hover_history[-51:]
        drift=None
        if len(self.body_hover_history)>=50:
            dt=(tick-self.body_hover_history[0][0])*.02
            drift=float(np.linalg.norm(self.body_hover_history[-1][1]-self.body_hover_history[0][1])/dt)
        original_ready=not m['desk_supported'] and m['object_bottom_m']>self.case['support_top_m']+.025 and q['qualified'] and q['hand_force_world_n'][2]>=.8*q['weight_n']
        self.stable=self.stable+1 if original_ready else 0
        if tick%5==0:self.events.append(dict(kind='body_grasp_hover_margin_and_drift',tick=tick,margins_m=margins,drift_m_s=drift,original_ready=bool(original_ready),quality=q))
        if self.stable>=50:
            minimum=float(self.case.get('body_min_rim_margin_m',.008));maximum=float(self.case.get('body_max_hover_drift_m_s',.002))
            if min(margins.values())<minimum:self.failure='body_grasp_insufficient_rim_margin';return
            if drift is None or drift>maximum:self.failure='body_grasp_continuing_drift';return
            self.grasp_test_passed=True;self.events.append(dict(kind='loaded_hover_passed',tick=tick,time_s=float(data.time),rim_margins_m=margins,drift_m_s=drift))
            self.object_lift_origin=np.array(m['object_m']);self.change('tuck',tick,data,m)
            self.move(tick,data,data.qpos[:3]+np.array(self.case['ready_arm_relative_m']),self.grasp_R,60)
        elif tick-self.start>150:self.failure='loaded_hover_unstable'
