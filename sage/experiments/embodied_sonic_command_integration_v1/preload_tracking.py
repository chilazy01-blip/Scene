"""Track measured loaded preload with original bounded finger position references."""
import numpy as np
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

ROLES=('thumb','index','middle')

def advance(previous,names,forces,goals,filtered):
    old=np.asarray(previous,dtype=float);out=old.copy();names=tuple(names)
    if old.shape!=(len(names),) or not np.isfinite(old).all() or len(names)!=len(set(names)):raise ValueError('invalid finger reference')
    if not all(g in v for v in (forces,goals,filtered) for g in ROLES):raise ValueError('complete measured group force and target required')
    if not np.isfinite([v[g] for v in (forces,goals,filtered) for g in ROLES]).all() or any(v[g]<0 for v in (forces,goals,filtered) for g in ROLES):raise ValueError('invalid force values')
    alpha=1-np.exp(-.02/.05);f={g:float(filtered[g]+alpha*(forces[g]-filtered[g])) for g in ROLES}
    delta={g:min(.006,.2*.02*max(0.,goals[g]-f[g])) for g in ROLES}
    for i,n in enumerate(names):
        if n not in RIGHT_CLOSED:continue
        end=RIGHT_CLOSED[n]*.5;lo,hi=min(0.,end),max(0.,end)
        if not lo-1e-12<=old[i]<=hi+1e-12:raise ValueError('finger outside original halfclosed reference envelope')
        out[i]=np.clip(old[i]+np.sign(end)*delta[group(n)],lo,hi)
    return out,f
