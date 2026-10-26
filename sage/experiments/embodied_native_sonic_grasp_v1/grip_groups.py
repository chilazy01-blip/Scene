"""Bounded per-contact-group position references under original native finger PD."""
import numpy as np
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group


def advance(values,forces,dt=.02,maximum=.50):
    if not np.isfinite(dt) or dt<0:raise ValueError('invalid sample interval')
    result={}
    for name,target_force in [('thumb',2.),('index',1.),('middle',1.)]:
        v=float(values[name]);f=float(forces[name])
        if not np.isfinite(v) or not np.isfinite(f):raise ValueError('nonfinite grasp feedback')
        result[name]=float(np.clip(v+(.20*dt if f<target_force else 0.),0,maximum))
    return result


def targets(names,values,release_ratio=1.):
    ratio=float(np.clip(release_ratio,0,1))
    return [float(RIGHT_CLOSED.get(n,0.)*values.get(group(n),0.)*ratio) for n in names]


def secure(forces):
    return forces['thumb']>=1. and forces['index']+forces['middle']>=1.
