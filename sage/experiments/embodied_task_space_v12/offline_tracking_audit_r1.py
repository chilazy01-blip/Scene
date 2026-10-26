"""Audit held-reference tracking at every saved physics substep.

This detects past domain exits. It does not predict or certify future dynamics.
The reference for post-state k is the reference actually applied at step k.
"""
import numpy as np

def audit_tracking(times, errors, lower, upper, active, names, physics_dt=.002, tolerance=1e-9):
    times=np.asarray(times,dtype=float);errors=np.asarray(errors,dtype=float)
    lower=np.asarray(lower,dtype=float);upper=np.asarray(upper,dtype=float)
    active=np.asarray(active,dtype=bool)
    if errors.ndim!=2 or times.shape!=(len(errors),) or errors.shape[1]!=len(names):
        raise ValueError('tracking_evidence_shape')
    if lower.shape!=upper.shape or lower.shape!=(len(names),) or active.shape!=lower.shape:
        raise ValueError('tracking_domain_shape')
    if not np.isfinite(errors).all() or not np.isfinite(times).all() or np.any(lower>upper):
        raise ValueError('tracking_evidence_finite_or_bounds')
    if len(times) and (abs(times[0]-physics_dt)>1e-10 or not np.allclose(np.diff(times),physics_dt,rtol=0,atol=1e-10)):
        raise ValueError('missing_or_misaligned_physics_substep')
    exceed=np.maximum(lower-errors,errors-upper);mask=(exceed>tolerance)&active[None,:]
    rows=[]
    for step,j in zip(*np.nonzero(mask)):
        rows.append(dict(step=int(step+1),time=float(times[step]),joint=str(names[j]),joint_index=int(j),error_rad=float(errors[step,j]),lower_rad=float(lower[j]),upper_rad=float(upper[j]),excess_rad=float(exceed[step,j])))
    return dict(passed=not rows,saved_substeps_audited=len(times),physics_dt=physics_dt,tolerance_rad=tolerance,first_violation=rows[0] if rows else None,violations=rows,violating_substeps=int(mask.any(axis=1).sum()),max_excess_rad=max(0.,float(exceed[:,active].max())) if len(errors) else 0.,scope='past_saved_states_only_no_future_invariance_certificate')
