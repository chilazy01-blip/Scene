"""Identify an unchanged terminal goal, independent of duplicate source indices."""
import numpy as np

def terminal_tail_start(first,last,sample,active_qpos,*,tolerance=1e-12):
    def signature(index):
        body,centers,rotations,hand=sample(float(index))
        keep=np.ones(len(body),dtype=bool);keep[active_qpos]=False
        return np.concatenate([np.asarray(body)[keep],np.ravel(centers),np.ravel(rotations),np.ravel(hand)])
    goal=signature(last);start=last
    while start>first and np.max(abs(signature(start-1)-goal))<=tolerance:start-=1
    return start
