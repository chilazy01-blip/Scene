"""Bounded source-phase progress and continuous rest-to-rest joint references."""
import numpy as np


def phase_progress(source_rows,control_rows,terminal_ticks=25):
    moving=control_rows-terminal_ticks
    if source_rows>moving or moving<3:raise ValueError('original_phase_budget_insufficient')
    ramp=max(1,min(50,(moving-source_rows+1)//2,moving//4))
    k=np.arange(moving);weights=np.minimum(np.minimum((k+1)/ramp,(moving-k)/ramp),1.)
    progress=np.r_[np.cumsum(weights)/weights.sum(),np.ones(terminal_ticks)]
    if np.max(np.diff(np.r_[0.,progress])*source_rows)>1+1e-12:raise ValueError('source_progress_rate')
    return progress,ramp


def interpolate_state(left,right,fraction):
    q=(1-fraction)*left+fraction*right
    for adr in (3,53):
        a=left[adr:adr+4];b=right[adr:adr+4]
        b=b if np.dot(a,b)>=0 else -b;v=(1-fraction)*a+fraction*b
        q[adr:adr+4]=v/np.linalg.norm(v)
    return q
