"""Actuator-aware, event-driven expert targets; no simulator state writes."""
import numpy as np
from scipy.spatial.transform import Rotation
from .phase_reference import interpolate,reference_qpos,rotation,yaw,angle_difference,Progress
from .object_relative_ik_r2 import UpperTargetSolver

class PhaseController:
    def __init__(self,model,inputs,palm_reference,inspection,plan):
        self.inputs=inputs;self.palms=palm_reference;self.groups=inspection['groups'];self.plan=plan;self.progress=Progress(plan,self.groups);self.solver=UpperTargetSolver(model,inputs['qpos_by_pin'],self.groups,plan);self.previous_target=None
        self.ratio=np.zeros(43)
        for r in inspection['hand_actuators']:self.ratio[r['pin_index']]=r['kd']/r['kp']
        for side in ['left','right']:
            c=inspection['controllers'][side]['attributes'];indices=self.groups[side+'_arm'];self.ratio[indices]=np.asarray(c['kd'])/np.asarray(c['kp'])
    def targets(self,actual_q,advance=True):
        p=self.progress;status=p.update(actual_q,self.inputs) if advance else dict(phase=p.phase,reasons=[],hold_seconds=p.hold_seconds);phase=p.phase;ref=reference_qpos(self.inputs,phase);by_pin=ref[self.inputs['qpos_by_pin']];pref=interpolate(self.palms[:,:,:3],phase);rotref=[]
        from .phase_reference import interpolate_quat
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
