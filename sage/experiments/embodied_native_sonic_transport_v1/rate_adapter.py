"""Legal range and command rate limiting for every SONIC-derived body joint."""
import numpy as np
from .protocol import project_target as original_project


def project_target(target,previous,lower,upper,max_step,allow_slew=False):
    if not allow_slew:return original_project(target,previous,lower,upper,max_step)
    candidate=np.asarray(target);previous=np.asarray(previous)
    if not np.isfinite(candidate).all() or not np.isfinite(previous).all():raise ValueError('nonfinite target')
    ranged=np.clip(candidate,lower,upper)
    # Original .543rad ceiling is preserved; command excess is handled, not executed.
    limited=previous+np.clip(ranged-previous,-max_step,max_step)
    limited=np.clip(limited,lower,upper)
    return limited,dict(maximum_projection_rad=float(np.max(np.abs(ranged-candidate))),
        maximum_step_rad=float(np.max(np.abs(limited-previous))),projected_joints=np.flatnonzero(ranged!=candidate).tolist(),
        maximum_requested_step_rad=float(np.max(np.abs(ranged-previous))),slew_limited_joints=np.flatnonzero(limited!=ranged).tolist())
