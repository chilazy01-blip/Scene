"""Persistent scalar finger-shape targets driven by measured normal force."""
import numpy as np

def update(closure,filtered_force,measured_force,desired_force,max_closed_angle,dt=.02):
    vals=np.array([closure,filtered_force,measured_force,desired_force,max_closed_angle,dt])
    if not np.isfinite(vals).all() or max_closed_angle<=0 or not 0<dt<=.02 or desired_force<0 or measured_force<0:raise ValueError('invalid normal feedback')
    filtered=filtered_force+(1-np.exp(-dt/.08))*(measured_force-filtered_force)
    error=desired_force-filtered
    if abs(error)<.05:error=0.
    delta=np.clip(dt*.35*error,-.006/max_closed_angle,.006/max_closed_angle)
    return float(np.clip(closure+delta,0,.5)),float(filtered)
