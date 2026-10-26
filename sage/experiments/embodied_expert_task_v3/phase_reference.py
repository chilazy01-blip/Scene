"""Fractional expert reference and event-driven progress without state resets."""
import numpy as np
from scipy.spatial.transform import Rotation,Slerp

def interpolate_quat(a,b,t):
    qa=np.roll(a,-1);qb=np.roll(b,-1)
    return np.roll(Slerp([0.,1.],Rotation.from_quat([qa,qb]))([t]).as_quat()[0],1)

def interpolate(values,phase):
    i=min(int(phase),len(values)-1);j=min(i+1,len(values)-1);mix=float(phase-i)
    return (1-mix)*values[i]+mix*values[j]

def reference_qpos(inputs,phase):
    q=interpolate(inputs['qpos'],phase);i=min(int(phase),len(inputs['qpos'])-1);j=min(i+1,len(inputs['qpos'])-1);mix=phase-i
    for start in (3,53):q[start:start+4]=interpolate_quat(inputs['qpos'][i,start:start+4],inputs['qpos'][j,start:start+4],mix)
    return q

def rotation(q):return Rotation.from_quat(np.roll(q,-1)).as_matrix()

def yaw(q):return float(Rotation.from_quat(np.roll(q,-1)).as_euler('xyz')[2])

def angle_difference(a,b):return float(np.arctan2(np.sin(a-b),np.cos(a-b)))

class Progress:
    def __init__(self,plan,groups):self.plan=plan;self.groups=groups;self.phase=0.;self.hold_seconds=0.;self.anchor=None;self.completed=False;self.last_target=None;self.last_qpos=None
    def update(self,actual,inputs):
        reason=[];arm_error=hand_error=object_error=0.
        if self.last_target is not None:
            q=actual[inputs['qpos_by_pin']];arm=self.groups['left_arm']+self.groups['right_arm'];hand=self.groups['left_hand']+self.groups['right_hand'];arm_error=float(np.max(np.abs(q[arm]-self.last_target[arm])));hand_error=float(np.max(np.abs(q[hand]-self.last_target[hand])))
            if arm_error>self.plan['arm_advance_tolerance_rad']:reason.append('arm_not_settled')
            if hand_error>self.plan['hand_advance_tolerance_rad']:reason.append('hand_not_settled')
            if self.phase>=self.plan['grasp_end_phase'] and self.phase<self.plan['release_phase'] and self.anchor is not None:
                target=reference_qpos(inputs,self.phase)[50:53]+self.anchor*self.anchor_weight();object_error=float(np.linalg.norm(actual[50:53]-target))
                if object_error>self.plan['transport_object_advance_tolerance_m']:reason.append('object_not_following')
        if reason:self.hold_seconds+=self.plan['control_dt']
        else:
            if self.last_target is not None:self.phase=min(921.,self.phase+self.plan['phase_rate'])
            self.hold_seconds=0.
        if self.anchor is None and self.phase>=self.plan['grasp_end_phase']:
            self.anchor=actual[50:53]-reference_qpos(inputs,self.phase)[50:53]
            if np.linalg.norm(self.anchor)>self.plan['max_grasp_anchor_offset_m']:reason.append('grasp_anchor_out_of_bounds')
        if self.hold_seconds>self.plan['max_hold_seconds']:reason.append('progress_timeout')
        return dict(phase=self.phase,hold_seconds=self.hold_seconds,reasons=reason,arm_error=arm_error,hand_error=hand_error,object_error=object_error)
    def anchor_weight(self):return float(np.clip((self.plan['release_phase']-self.phase)/(self.plan['release_phase']-self.plan['grasp_end_phase']),0,1))
