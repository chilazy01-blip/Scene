"""LP reduction justified by variable bounds and exactly proportional rows.

Every returned certificate is checked against the untouched original problem.
"""
import math
import time

import numpy as np
from scipy import sparse
from scipy.optimize import linprog

from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals, residual_gate


def reduce_rows(A, low, high):
    A = A.tocsr()
    n = A.shape[1]
    assert (A[-n:] - sparse.eye(n, format="csr")).nnz == 0
    B = A[:-n].copy()
    B.eliminate_zeros()
    B.sort_indices()
    lb, ub = low[-n:], high[-n:]
    counts = np.diff(B.indptr)
    row = np.repeat(np.arange(B.shape[0]), counts)
    v, col = B.data, B.indices
    lower_terms = v * np.where(v > 0, lb[col], ub[col])
    upper_terms = v * np.where(v > 0, ub[col], lb[col])
    minimum = np.bincount(row, weights=lower_terms, minlength=B.shape[0])
    maximum = np.bincount(row, weights=upper_terms, minlength=B.shape[0])
    magnitude = np.bincount(row, weights=np.maximum(abs(lower_terms), abs(upper_terms)), minlength=B.shape[0])
    finite_bound = np.maximum(np.where(np.isfinite(low[:-n]), abs(low[:-n]), 0.), np.where(np.isfinite(high[:-n]), abs(high[:-n]), 0.))
    # Conservative summation/product allowance, then outward rounding.
    padding = 8 * np.finfo(float).eps * (counts + 1) * (magnitude + finite_bound + 1)
    minimum = np.nextafter(minimum - padding, -np.inf)
    maximum = np.nextafter(maximum + padding, np.inf)
    lower_implied = (~np.isfinite(low[:-n])) | (minimum >= low[:-n])
    upper_implied = (~np.isfinite(high[:-n])) | (maximum <= high[:-n])
    redundant = lower_implied & upper_implied
    # Remove only individually proved redundant sides. The other side remains.
    effective_low = low.copy()
    effective_high = high.copy()
    effective_low[np.flatnonzero(lower_implied)] = -np.inf
    effective_high[np.flatnonzero(upper_implied)] = np.inf
    keep = np.flatnonzero(~redundant)
    groups = {}
    representatives, factors, lo, hi, lower_owner, upper_owner = [], [], [], [], [], []
    for i in keep:
        a, b = B.indptr[i:i + 2]
        values = B.data[a:b]
        if not len(values):
            assert low[i] <= 0 <= high[i], "inconsistent_constant_row"
            continue
        factor = math.ldexp(1., -math.frexp(float(np.max(abs(values))))[1])
        if values[0] < 0:
            factor = -factor
        scaled = values * factor
        # Reject a normalization that loses floating point information.
        if not np.array_equal(scaled / factor, values):
            factor = 1.
            scaled = values
        key = (B.indices[a:b].tobytes(), scaled.tobytes())
        l, h = (effective_low[i] * factor, effective_high[i] * factor) if factor > 0 else (effective_high[i] * factor, effective_low[i] * factor)
        if key not in groups:
            groups[key] = len(representatives)
            representatives.append(i)
            factors.append(factor)
            lo.append(l)
            hi.append(h)
            lower_owner.append((i, factor))
            upper_owner.append((i, factor))
        else:
            k = groups[key]
            if l > lo[k]:
                lo[k] = l
                lower_owner[k] = (i, factor)
            if h < hi[k]:
                hi[k] = h
                upper_owner[k] = (i, factor)
    reduced = B[np.array(representatives, dtype=int)].multiply(np.asarray(factors)[:, None]).tocsr()
    lo, hi = np.asarray(lo), np.asarray(hi)
    assert np.all(lo <= hi), "inconsistent_exact_row_intersection"
    info = dict(box_implied_lower_sides=int(np.sum(lower_implied & np.isfinite(low[:-n]))),box_implied_upper_sides=int(np.sum(upper_implied & np.isfinite(high[:-n]))),maximum_reduced_finite_bound=float(np.max(np.r_[abs(lo[np.isfinite(lo)]),abs(hi[np.isfinite(hi)])],initial=0)),original_rows=A.shape[0],box_implied_rows=int(redundant.sum()),exact_duplicate_rows=len(keep)-len(representatives),retained_nonbound_rows=len(representatives),native_bound_rows=n,fixed_variables=int(np.sum(lb==ub)))
    mapping = dict(lower_owner=np.asarray(lower_owner),upper_owner=np.asarray(upper_owner),box_implied=np.flatnonzero(redundant))
    return reduced, lo, hi, mapping, info
