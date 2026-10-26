"""Discrete private reference stopping, not physical body stopping."""
import numpy as np

def factors(velocity, acceleration, dt=.02):
    velocity=np.asarray(velocity,dtype=float);acceleration=np.asarray(acceleration,dtype=float)
    if velocity.shape!=acceleration.shape or not np.isfinite(velocity).all() or not np.isfinite(acceleration).all() or np.any(acceleration<=0) or not np.isfinite(dt) or dt<=0:raise ValueError('invalid_stopping_input')
    duration=float(np.max(abs(velocity)/acceleration,initial=0.))
    if duration==0:return []
    return [max(0.,1-k*dt/duration) for k in range(1,int(np.ceil(duration/dt))+1)]

def displacement_factor(speed_limit, acceleration, dt=.02):
    speed_limit=np.asarray(speed_limit,dtype=float);acceleration=np.asarray(acceleration,dtype=float)
    if speed_limit.shape!=acceleration.shape or not np.isfinite(speed_limit).all() or not np.isfinite(acceleration).all() or np.any(speed_limit<0) or np.any(acceleration<=0) or not np.isfinite(dt) or dt<=0:raise ValueError('invalid_stopping_limits')
    return 1+float(np.max(speed_limit/acceleration,initial=0.))/(2*dt)
