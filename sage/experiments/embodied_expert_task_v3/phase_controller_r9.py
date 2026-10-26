"""Actuator-aware, event-driven expert targets; no simulator state writes."""
import numpy as np
from scipy.spatial.transform import Rotation
from .phase_reference_r2 import interpolate,reference_qpos,rotation,yaw,angle_difference,Progress
from .object_relative_ik_r7 import UpperTargetSolver

class BasePhaseController:
    def __init__(self,model,inputs,palm_reference,inspection,plan):
        self.inputs=inputs;self.palms=palm_reference;self.groups=inspection['groups'];self.plan=plan;self.progress=Progress(plan,self.groups);self.solver=UpperTargetSolver(model,inputs['qpos_by_pin'],self.groups,plan);self.previous_target=None
        self.ratio=np.zeros(43)
        for r in inspection['hand_actuators']:self.ratio[r['pin_index']]=r['kd']/r['kp']
        for side in ['left','right']:
            c=inspection['controllers'][side]['attributes'];indices=self.groups[side+'_arm'];self.ratio[indices]=np.asarray(c['kd'])/np.asarray(c['kp'])
    def targets(self,actual_q,advance=True):
        p=self.progress;status=p.update(actual_q,self.inputs) if advance else dict(phase=p.phase,reasons=[],hold_seconds=p.hold_seconds);phase=p.phase;ref=reference_qpos(self.inputs,phase);by_pin=ref[self.inputs['qpos_by_pin']];pref=interpolate(self.palms[:,:,:3],phase);rotref=[]
        from .phase_reference_r2 import interpolate_quat
        i=min(int(phase),921);j=min(i+1,921)
        for side in range(2):rotref.append(rotation(interpolate_quat(self.palms[i,side,3:],self.palms[j,side,3:],phase-i)))
        actual_R=rotation(actual_q[53:57]);ref_R=rotation(ref[53:57]);delta_R=actual_R@ref_R.T
        if phase<self.plan['grasp_end_phase']:
            target_position=actual_q[50:53];target_R=actual_R
        elif phase<self.plan['release_phase']:
            anchor=np.zeros(3) if p.anchor is None else p.anchor*p.anchor_weight();goal=ref[50:53]+anchor;delta=goal-actual_q[50:53];delta*=min(1.,self.plan['max_object_goal_step_m']/max(np.linalg.norm(delta),1e-12));target_position=actual_q[50:53]+delta
            rv=Rotation.from_matrix(ref_R@actual_R.T).as_rotvec();rv*=min(1.,self.plan['object_orientation_step_rad']/max(np.linalg.norm(rv),1e-12));target_R=Rotation.from_rotvec(rv).as_matrix()@actual_R
        else:target_position=ref[50:53];target_R=ref_R
        positions=np.asarray([target_position+target_R@ref_R.T@(pos-ref[50:53]) for pos in pref]);rotations=np.asarray([target_R@ref_R.T@r for r in rotref]);target,ik=self.solver.solve(actual_q,by_pin,positions,rotations);velocity=np.zeros(43) if self.previous_target is None else (target-self.previous_target)/self.plan['control_dt'];upper=np.asarray(sorted(set(self.groups['upper_body'])-set(self.groups['lower_body'])));command=target.copy();command[upper]+=self.ratio[upper]*velocity[upper];command=np.clip(command,self.inputs['native_lower_limits'],self.inputs['native_upper_limits']);self.previous_target=target.copy();p.last_target=target.copy();p.last_qpos=ik['qpos'].copy()
        nav=interpolate(self.inputs['navigate'],min(phase,920))*self.plan['phase_rate'];theta=yaw(actual_q[3:7]);ref_theta=yaw(ref[3:7]);actual_yaw_R=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]);ref_yaw_R=np.array([[np.cos(ref_theta),-np.sin(ref_theta)],[np.sin(ref_theta),np.cos(ref_theta)]]);nav[:2]=actual_yaw_R.T@(ref_yaw_R@nav[:2]+self.plan['root_position_gain']*(ref[:2]-actual_q[:2]));nav[2]+=self.plan['root_yaw_gain']*angle_difference(ref_theta,theta);nav[:2]=np.clip(nav[:2],-self.plan['max_nav_xy_mps'],self.plan['max_nav_xy_mps']);nav[2]=np.clip(nav[2],-self.plan['max_nav_yaw_rps'],self.plan['max_nav_yaw_rps'])
        if p.hold_seconds>0:nav[:2]-=actual_yaw_R.T@(ref_yaw_R@interpolate(self.inputs['navigate'],min(phase,920))[:2])*self.plan['phase_rate'];nav[2]-=interpolate(self.inputs['navigate'],min(phase,920))[2]*self.plan['phase_rate']
        nav[:2]=np.clip(nav[:2],-self.plan['max_nav_xy_mps'],self.plan['max_nav_xy_mps']);nav[2]=np.clip(nav[2],-self.plan['max_nav_yaw_rps'],self.plan['max_nav_yaw_rps'])
        goal=dict(navigate_cmd=nav,base_height_command=interpolate(self.inputs['height'],min(phase,920)),wrist_pose=interpolate(self.inputs['wrist'],min(phase,920)),target_upper_body_pose=target[self.groups['upper_body']].copy())
        diag=dict(progress=status,ik={k:v for k,v in ik.items() if k!='qpos'},phase=phase,target=target.copy(),feedforward_velocity=velocity,goal=goal)
        return goal,command,diag
    def combine(self,native_action,upper_command):
        q=native_action['q'].copy();lower=self.groups['lower_body'];upper=sorted(set(self.groups['upper_body'])-set(lower));q[lower]+=interpolate(self.inputs['offsets'],self.progress.phase)[lower];q[upper]=upper_command[upper];return dict(q=np.clip(q,self.inputs['native_lower_limits'],self.inputs['native_upper_limits']))


class PhaseController(BasePhaseController):
    """Pause a pregrasp reach that cannot fit the arm workspace and move the base.

    Holding means a bounded position command at the observed arm/hand pose.
    Its geometry is independently checked; physical stability is not assumed.
    """
    def targets(self,actual_q,advance=True):
        old_phase=self.progress.phase;already_holding=self.progress.external_hold
        goal,command,diag=super().targets(actual_q,advance=advance)
        p=self.progress;diag['control_mode']='track_object_relative_target'
        diag['control_target_passed']=diag['ik']['passed']
        if diag['ik']['passed']:
            p.external_hold=False
            if p.phase>=921.:goal['navigate_cmd']=np.zeros(3)
            return goal,command,diag
        p.external_hold=True
        if not p.phase<self.plan['grasp_end_phase']:
            return goal,command,diag
        import mujoco
        from sage.experiments.embodied_expert_task_v1.quality import contacts,kinematics
        p.phase=old_phase
        if advance and not already_holding:p.hold_seconds+=self.plan['control_dt']
        ref=reference_qpos(self.inputs,p.phase);offset=actual_q[50:52]-ref[50:52]
        if np.linalg.norm(offset)>self.plan['max_pregrasp_reposition_m']:
            diag['control_mode']='rejected_reposition_bound';return goal,command,diag
        target=np.clip(actual_q[self.inputs['qpos_by_pin']],self.inputs['native_lower_limits'],self.inputs['native_upper_limits'])
        data=self.solver.data;data.qpos[:]=actual_q;data.qpos[self.solver.qids]=target[self.solver.upper];data.qvel[:]=0;mujoco.mj_forward(self.solver.model,data)
        con=contacts(self.solver.model,data,self.solver.names,self.solver.roles,self.plan['physical_limits']);kin=kinematics(self.solver.model,data,self.plan['physical_limits']);issues=con['violations']+kin['violations']
        diag['hold_target_validation']=dict(passed=not issues,violations=issues,scope='observed-pose geometry only; no prediction of physical stability')
        diag['control_target_passed']=not issues;diag['control_mode']='hold_pregrasp_and_reposition_base'
        theta=yaw(actual_q[3:7]);R=np.array([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]]);error=ref[:2]+offset-actual_q[:2];nav=np.zeros(3);nav[:2]=R.T@error*self.plan['root_position_gain'];distance=np.linalg.norm(error)
        if distance>self.plan['pregrasp_reposition_tolerance_m']:
            speed=max(self.plan['pregrasp_reposition_min_speed_mps'],float(np.linalg.norm(nav[:2])));nav[:2]=speed*nav[:2]/max(np.linalg.norm(nav[:2]),1e-12)
        nav[:2]=np.clip(nav[:2],-self.plan['max_nav_xy_mps'],self.plan['max_nav_xy_mps']);nav[2]=np.clip(self.plan['root_yaw_gain']*angle_difference(yaw(ref[3:7]),theta),-self.plan['max_nav_yaw_rps'],self.plan['max_nav_yaw_rps'])
        goal['navigate_cmd']=nav;goal['target_upper_body_pose']=target[self.groups['upper_body']].copy()
        self.previous_target=target.copy();p.last_target=target.copy();p.last_qpos=data.qpos.copy();diag.update(target=target.copy(),feedforward_velocity=np.zeros(43),goal=goal,phase=p.phase,reposition_error=error.copy())
        diag['progress'].update(phase=p.phase,hold_seconds=p.hold_seconds)
        if 'retarget_not_feasible' not in diag['progress']['reasons']:diag['progress']['reasons'].append('retarget_not_feasible')
        if p.hold_seconds>self.plan['max_hold_seconds'] and 'progress_timeout' not in diag['progress']['reasons']:diag['progress']['reasons'].append('progress_timeout')
        return goal,target.copy(),diag
