"""Use available original halfclosed index0 reference reserve after shape saturation."""
import numpy as np

def advance(extra,base,filtered,request,original_cap,dt=.02):
    vals=np.array([extra,base,filtered,request,original_cap,dt])
    if not np.isfinite(vals).all() or extra<0 or base>original_cap or not 0<dt<=.02:raise ValueError('invalid native index reserve input')
    error=request-filtered
    change=0. if error<.05 else min(.006,dt*.35*1.4*error)
    return float(min(original_cap-base,extra+change))
