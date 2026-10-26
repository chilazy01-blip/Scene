"""Frozen expert schedule, with a one-second terminal settling segment."""
import numpy as np
from .expert_offset import source_goal

def goal_at(source,inputs,robot_model,index):
    count=source['count'];goal=source_goal(source,min(index,count-1))
    if index>=count:
        mix=min(1.,(index-count+1)/10.)
        upper=robot_model.get_joint_group_indices('upper_body')
        native_source_final=source['arrays']['states'][-1,1+inputs['qpos_by_pin']]
        goal['target_upper_body_pose']=(1-mix)*goal['target_upper_body_pose']+mix*native_source_final[upper]
        goal['navigate_cmd']=(1-mix)*goal['navigate_cmd']
    return goal

def correction_at(inputs,index):return inputs['offsets'][min(index,len(inputs['offsets'])-1)].copy()

def reference_state_at(source,inputs,index):
    i=min(index,len(inputs['qpos'])-1);vel=inputs['qvel'][i].copy() if index<len(inputs['qpos']) else np.zeros_like(inputs['qvel'][i])
    return np.r_[index*source['control_dt'],inputs['qpos'][i],vel]
