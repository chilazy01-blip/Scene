"""Normalize a native-mesh grasp shape inside the existing half-closed envelope."""
import numpy as np
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
ROLES=('thumb','index','middle')
def from_shape(names,angles):
    if set(names)!=set(RIGHT_CLOSED):raise ValueError('incomplete native right-hand shape')
    values=dict(zip(names,map(float,angles)));ratios={n:values[n]/RIGHT_CLOSED[n] for n in names}
    if not np.isfinite(list(ratios.values())).all() or any(v<0 or v>.5 for v in ratios.values()):raise ValueError('shape exceeds original sign or half-closed reference envelope')
    touch={g:max(ratios[n] for n in names if group(n)==g) for g in ROLES}
    if min(touch.values())<=0:raise ValueError('degenerate finger shape')
    template={n:values[n]/touch[group(n)] for n in names}
    return template,touch

def targets(names,template,closures):
    if not all(np.isfinite(closures[g]) and 0<=closures[g]<=.5 for g in ROLES):raise ValueError('invalid group closure')
    q=np.array([template.get(n,0)*closures.get(group(n),0) for n in names])
    for n,v in zip(names,q):
        if n in RIGHT_CLOSED and not min(0,RIGHT_CLOSED[n]*.5)-1e-12<=v<=max(0,RIGHT_CLOSED[n]*.5)+1e-12:raise ValueError('native hand reference envelope violation')
    return q
