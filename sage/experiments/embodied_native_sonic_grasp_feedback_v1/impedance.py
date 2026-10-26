"""Anchored force feedforward plus measured force-error integral; no qactual reset."""
import numpy as np

def update(reference,anchor,integral,friction_estimate,desired_contact,measured_contact,bias,native_friction,kp,lo,hi,dt=.02):
    a=dt/(.10+dt);friction=(1-a)*np.asarray(friction_estimate)+a*np.asarray(native_friction)
    error=np.asarray(desired_contact)-measured_contact;candidate=np.asarray(integral)+2.*dt*error
    ff=np.asarray(desired_contact)+bias-friction;raw=np.asarray(anchor)+(ff+candidate)/kp
    bounded=np.clip(raw,lo,hi);blocked=((raw>hi)&(error>0))|((raw<lo)&(error<0));candidate=np.where(blocked,integral,candidate)
    raw=np.asarray(anchor)+(ff+candidate)/kp;target=np.clip(np.asarray(reference)+np.clip(raw-reference,-.006,.006),lo,hi)
    if not np.isfinite(np.r_[target,candidate,friction]).all():raise ValueError('nonfinite impedance reference')
    return target,candidate,friction,dict(raw_target_rad=raw.tolist(),feedforward_torque_nm=ff.tolist(),integral_torque_nm=candidate.tolist(),friction_estimate_nm=friction.tolist(),explicit_PD_position_and_velocity_feedback_retained=True)
