"""A reference-continuous lift starts from the prior desired endpoint."""
import numpy as np

def make_path(tick,position,rotation,goal,goal_rotation,duration=60):
    p=np.array(position,dtype=float);R=np.array(rotation,dtype=float);g=np.array(goal,dtype=float);G=np.array(goal_rotation,dtype=float)
    if not np.isfinite(np.r_[p,g,R.ravel(),G.ravel()]).all() or duration<=0:raise ValueError('invalid continuous lift')
    return dict(tick=tick,duration=duration,origin=p.copy(),initial_R=R.copy(),goal=g.copy(),R=G.copy())
