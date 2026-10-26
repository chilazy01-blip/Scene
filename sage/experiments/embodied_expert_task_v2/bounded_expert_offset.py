"""Native joint-limit enforcement after the single frozen reference offset."""
import numpy as np
from .expert_offset import make_runtime,qpos_mapping,source_goal,apply_offset

def bounded_action(action,offset,lower,upper):
    raw=apply_offset(action,offset)['q'];lo=np.asarray(lower);hi=np.asarray(upper)
    if lo.shape!=(43,) or hi.shape!=(43,) or not np.isfinite(lo).all() or not np.isfinite(hi).all() or np.any(lo>=hi):raise ValueError('invalid native joint range')
    bounded=np.clip(raw,lo,hi)
    return dict(q=bounded),dict(raw_corrected=raw.copy(),clipping=bounded-raw,clipped_indices=np.flatnonzero(bounded!=raw).tolist())
