"""Native-range reserve for the declared uniform reference stopping ramp.

Intersect these bounds with the current acceleration/error/collision intervals.
They do not establish whole-task feasibility or physical stopping safety.
"""
import numpy as np
from .stopping import displacement_factor


def native_stopping_increment_bounds(reference, lower, upper, speed_limit, acceleration, dt=.02):
    ref,lo,hi,speed,acc=[np.asarray(x,dtype=float) for x in (reference,lower,upper,speed_limit,acceleration)]
    if any(x.shape!=ref.shape or not np.isfinite(x).all() for x in (lo,hi,speed,acc)) or not np.isfinite(ref).all() or np.any(lo>hi) or np.any(ref<lo) or np.any(ref>hi):
        raise ValueError('invalid_native_stopping_domain')
    factor=displacement_factor(speed,acc,dt)
    return np.maximum((lo-ref)/factor,-speed*dt),np.minimum((hi-ref)/factor,speed*dt)
