"""Absolute repaired arm/hand targets with native WBC leg and waist control.

This postprocessor copies its input and does not modify WBC recurrent state.
Counterfactual NN reuse is valid only for identical goals/observations/history.
Real physics must always evaluate the native WBC from fresh observations.
"""
import numpy as np
from .bounded_expert_offset import bounded_action

def direct_action(action,offset,reference_by_pin,lower,upper,direct_indices):
    indices=np.asarray(direct_indices,dtype=int);reference=np.asarray(reference_by_pin)
    if indices.shape!=(28,) or len(set(indices))!=28 or reference.shape!=(43,) or not np.isfinite(reference).all():
        raise ValueError('invalid absolute arm/hand target')
    out,diag=bounded_action(action,offset,lower,upper)
    out['q'][indices]=np.clip(reference[indices],lower[indices],upper[indices])
    diag['direct_reference_clip']=out['q'][indices]-reference[indices]
    return out,diag
