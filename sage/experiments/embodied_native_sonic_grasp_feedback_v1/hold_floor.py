"""Preserve established closure during load, using original bounded references."""
import numpy as np
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

def project(previous,proposed,floor):
    p=np.array([previous[g] for g in ('thumb','index','middle')]);q=np.array([proposed[g] for g in ('thumb','index','middle')]);f=np.array([floor[g] for g in ('thumb','index','middle')])
    if not np.isfinite(np.r_[p,q,f]).all() or np.any(p<0) or np.any(p>.5) or np.any(f<0) or np.any(f>p+1e-12):raise ValueError('invalid loaded grip floor')
    maximum=np.array([max(abs(v) for n,v in RIGHT_CLOSED.items() if group(n)==g) for g in ('thumb','index','middle')]);new=np.clip(np.maximum(q,f),np.maximum(0,p-.006/maximum),np.minimum(.5,p+.006/maximum));new=np.maximum(new,f)
    return {g:float(v) for g,v in zip(('thumb','index','middle'),new)}
