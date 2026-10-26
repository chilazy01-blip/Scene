"""Offline readiness predicate for an actuator-aware, object-relative successor.

This is an observer, not a controller. A HOLD does not certify that waiting is
safe: the successor must independently generate a feasible hold/contact action.
"""
import numpy as np

def evaluate_progress(actual_by_pin,target_by_pin,actual_object,reference_object,joint_names,hand_tolerance=.1,object_tolerance=.005):
    actual=np.asarray(actual_by_pin);target=np.asarray(target_by_pin);obj=np.asarray(actual_object);ref=np.asarray(reference_object)
    if actual.shape!=(43,) or target.shape!=(43,) or obj.shape!=(3,) or ref.shape!=(3,) or len(joint_names)!=43:raise ValueError('invalid progress observer input')
    if not all(np.isfinite(a).all() for a in (actual,target,obj,ref)):raise ValueError('nonfinite progress observer input')
    hands=np.asarray([k for k,name in enumerate(joint_names) if '_hand_' in name]);assert len(hands)==14
    error=float(np.max(np.abs(actual[hands]-target[hands])));object_error=float(np.linalg.norm(obj-ref));reasons=[]
    if error>hand_tolerance:reasons.append('hand_not_settled')
    if object_error>object_tolerance:reasons.append('object_pose_departed')
    return dict(advance=not reasons,reasons=reasons,hand_error_rad=error,object_position_error_m=object_error,holding_action_certified=False)
