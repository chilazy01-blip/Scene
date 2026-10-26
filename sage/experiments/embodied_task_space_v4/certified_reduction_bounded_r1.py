"""Equivalent reduced LP with downward-only original-row scaling.

The saved diagnosis found canonical row multipliers up to 2**47. Canonical
normalization remains an exact duplicate key, but is undone before solving.
Every candidate must still satisfy the untouched full original LP certificate.
"""
import time
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .certified_reduction import reduce_rows
from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals, residual_gate


def solver_rows(A, low, high):
    B, lo, hi, mapping, info = reduce_rows(A, low, high)
    owner_max = np.maximum(abs(mapping['lower_owner'][:, 1]), abs(mapping['upper_owner'][:, 1]))
    finite_bound = np.maximum(np.where(np.isfinite(lo), abs(lo), 0.), np.where(np.isfinite(hi), abs(hi), 0.))
    peak = np.maximum(1., np.maximum(owner_max, finite_bound))
    scale = np.exp2(-np.ceil(np.log2(peak)))
    if not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError('nonrepresentable_row_scaling')
    counts = np.diff(B.indptr)
    data_scale = np.repeat(scale, counts)
    before = B.data.copy()
    B.data *= data_scale
    if not np.array_equal(B.data / data_scale, before):
        raise ValueError('row_scaling_loses_coefficient_information')
    ll, hh = lo * scale, hi * scale
    if not np.array_equal(ll / scale, lo) or not np.array_equal(hh / scale, hi):
        raise ValueError('row_scaling_loses_bound_information')
    info = dict(info, maximum_canonical_multiplier=float(owner_max.max()),
                maximum_effective_original_multiplier=float(np.max(owner_max * scale)),
                row_downscale_min=float(scale.min()), row_downscale_max=float(scale.max()),
                maximum_scaled_finite_bound=float(np.max(np.r_[abs(ll[np.isfinite(ll)]), abs(hh[np.isfinite(hh)])])),
                coefficients_below_1e9=int(np.sum(abs(B.data) < 1e-9)),
                equivalent_positive_power_two_scaling=True)
    return B, ll, hh, mapping, scale, info


def solve_lp(cost, A, low, high, seconds, callback=None):
    started = time.monotonic()
    A = A.tocsr()
    n = len(cost)
    B, lo, hi, mapping, scale, info = solver_rows(A, low, high)
    if callback:
        callback(info)
    upper, lower = np.flatnonzero(np.isfinite(hi)), np.flatnonzero(np.isfinite(lo))
    C = sparse.vstack([B[upper], -B[lower]], format='csr')
    rhs = np.r_[hi[upper], -lo[lower]]
    preprocessing = time.monotonic() - started
    remaining = seconds - preprocessing
    if remaining <= .1:
        return None, None, dict(passed=False, status='preprocessing_deadline', seconds=preprocessing, reduction=info)
    options = dict(time_limit=remaining, presolve=True,
                   primal_feasibility_tolerance=1e-10, dual_feasibility_tolerance=1e-10)
    ans = linprog(cost, A_ub=C, b_ub=rhs, bounds=list(zip(low[-n:], high[-n:])), method='highs-ds', options=options)
    result = dict(passed=False, status=ans.message, status_code=int(ans.status),
                  seconds=time.monotonic()-started, preprocessing_seconds=preprocessing,
                  iterations=int(ans.nit), reduction=info, options=options,
                  numerical_backend='proved_reduction_downward_original_row_scaling_dual_simplex_r1')
    if ans.x is None or ans.ineqlin.marginals is None:
        return None, None, result
    primal = ans.x
    reduced_dual = np.zeros(B.shape[0])
    np.add.at(reduced_dual, upper, -ans.ineqlin.marginals[:len(upper)]*scale[upper])
    np.add.at(reduced_dual, lower, ans.ineqlin.marginals[len(upper):]*scale[lower])
    owner = np.where((reduced_dual >= 0)[:, None], mapping['upper_owner'], mapping['lower_owner'])
    dual = np.zeros(A.shape[0])
    np.add.at(dual, owner[:, 0].astype(int), reduced_dual*owner[:, 1])
    dual[-n:] = -ans.lower.marginals-ans.upper.marginals
    zero = sparse.csr_matrix((n, n))
    original = qp_residuals(zero, cost, A, low, high, primal, dual)
    result['before_polish'] = original
    if not residual_gate(original):
        proposal = dual.copy()
        proposal[-n:] -= cost + A.T@dual
        metrics = qp_residuals(zero, cost, A, low, high, primal, proposal)
        result['polish_metrics'] = metrics
        if residual_gate(metrics):
            dual, original = proposal, metrics
    result.update(passed=bool(ans.success and residual_gate(original)), residuals=original,
                  objective=float(cost@primal), all_original_rows_verified=True)
    return primal, dual, result
