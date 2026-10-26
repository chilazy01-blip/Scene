"""Reference changes admitted by an error box at command emission only.

If e is the old tracking error and d is the reference change, the instantaneous
new error is e - d. No future-state or contact guarantee follows from this
algebra; a causal tracking certificate must be supplied separately.
"""
import numpy as np


def admitted_delta_interval(error_lower, error_upper, domain_lower, domain_upper):
    """Return d such that every old error in the box stays in the domain.

    Each coordinate must satisfy error_upper - domain_upper <= d and
    d <= error_lower - domain_lower. An inverted interval is infeasible.
    The function does not assume independent joint dynamics.
    """
    arrays = [np.asarray(value, dtype=np.float64) for value in
              (error_lower, error_upper, domain_lower, domain_upper)]
    if any(value.shape != (43,) or not np.isfinite(value).all() for value in arrays):
        raise ValueError("error_box_shape_finite")
    error_lo, error_hi, domain_lo, domain_hi = arrays
    if np.any(error_lo > error_hi) or np.any(domain_lo > domain_hi):
        raise ValueError("error_box_order")
    lower = error_hi - domain_hi
    upper = error_lo - domain_lo
    return lower, upper


def uniform_step_limit(error, proposed_delta, lower, upper, active):
    """Largest alpha in [0, 1] for an admitted alpha * proposed_delta.

    This is a diagnostic of instantaneous feasibility, not a runtime rate
    limiter: making a rejected step smaller does not qualify future tracking.
    """
    arrays = [np.asarray(value, dtype=np.float64)
              for value in (error, proposed_delta, lower, upper)]
    mask = np.asarray(active, dtype=bool)
    if (mask.shape != (43,) or
            any(value.shape != (43,) or not np.isfinite(value).all() for value in arrays)):
        raise ValueError("step_shape_finite")
    observed_error, delta, domain_lo, domain_hi = arrays
    if np.any(domain_lo > domain_hi):
        raise ValueError("domain_order")
    if np.any(mask & ((observed_error < domain_lo) | (observed_error > domain_hi))):
        raise ValueError("observed_error_outside_domain")
    candidates = np.ones(43, dtype=np.float64)
    positive = mask & (delta > 0)
    negative = mask & (delta < 0)
    candidates[positive] = (observed_error[positive] - domain_lo[positive]) / delta[positive]
    candidates[negative] = (domain_hi[negative] - observed_error[negative]) / -delta[negative]
    return float(np.clip(candidates.min(), 0.0, 1.0))
