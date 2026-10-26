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
    redundant = ((~np.isfinite(low[:-n])) | (minimum >= low[:-n])) & ((~np.isfinite(high[:-n])) | (maximum <= high[:-n]))
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
        l, h = (low[i] * factor, high[i] * factor) if factor > 0 else (high[i] * factor, low[i] * factor)
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
    info = dict(original_rows=A.shape[0],box_implied_rows=int(redundant.sum()),exact_duplicate_rows=len(keep)-len(representatives),retained_nonbound_rows=len(representatives),native_bound_rows=n,fixed_variables=int(np.sum(lb==ub)))
    mapping = dict(lower_owner=np.asarray(lower_owner),upper_owner=np.asarray(upper_owner),box_implied=np.flatnonzero(redundant))
    return reduced, lo, hi, mapping, info


def solve_lp(cost, A, low, high, seconds, callback=None):
    started = time.monotonic()
    A = A.tocsr()
    n = len(cost)
    B, lo, hi, mapping, info = reduce_rows(A, low, high)
    if callback:
        callback(info)
    # Exact power-of-two equilibration; original identity bounds stay native.
    D = np.ones(n)
    S = np.ones(B.shape[0])
    for _ in range(4):
        maximum = np.asarray(abs(B).max(axis=0).toarray()).ravel()
        delta = np.exp2(np.clip(np.rint(-.5*np.log2(np.maximum(maximum, 1e-12))), -20, 20))
        new = np.clip(D*delta, 2.**-20, 2.**20)
        B = B.multiply(new/D).tocsr()
        D = new
        maximum = np.asarray(abs(B).max(axis=1).toarray()).ravel()
        delta = np.exp2(np.clip(np.rint(-.5*np.log2(np.maximum(maximum, 1e-12))), -20, 20))
        new = np.clip(S*delta, 2.**-20, 2.**20)
        B = B.multiply((new/S)[:,None]).tocsr()
        S = new
    upper = np.flatnonzero(np.isfinite(hi))
    lower = np.flatnonzero(np.isfinite(lo))
    C = sparse.vstack([B[upper], -B[lower]],format="csr")
    rhs = np.r_[hi[upper]*S[upper], -lo[lower]*S[lower]]
    preprocessing = time.monotonic()-started
    remaining = seconds-preprocessing
    if remaining <= .1:
        return None,None,dict(passed=False,status="preprocessing_deadline",seconds=preprocessing,reduction=info)
    ans = linprog(cost*D,A_ub=C,b_ub=rhs,bounds=list(zip(low[-n:]/D,high[-n:]/D)),method="highs-ipm",options=dict(time_limit=remaining,presolve=True,ipm_optimality_tolerance=1e-10,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
    result = dict(passed=False,status=ans.message,status_code=int(ans.status),seconds=time.monotonic()-started,preprocessing_seconds=preprocessing,iterations=int(ans.nit),reduction=info,numerical_backend="proved_box_duplicate_reduction_scaled_ipm")
    if ans.x is None or ans.ineqlin.marginals is None:
        return None,None,result
    primal = ans.x*D
    reduced_dual = np.zeros(B.shape[0])
    np.add.at(reduced_dual,upper,-ans.ineqlin.marginals[:len(upper)]*S[upper])
    np.add.at(reduced_dual,lower,ans.ineqlin.marginals[len(upper):]*S[lower])
    owner = np.where((reduced_dual >= 0)[:,None],mapping["upper_owner"],mapping["lower_owner"])
    dual = np.zeros(A.shape[0])
    np.add.at(dual,owner[:,0].astype(int),reduced_dual*owner[:,1])
    dual[-n:] = (-ans.lower.marginals-ans.upper.marginals)/D
    zero = sparse.csr_matrix((n,n))
    original = qp_residuals(zero,cost,A,low,high,primal,dual)
    result["before_polish"] = original
    if not residual_gate(original):
        proposal = dual.copy()
        proposal[-n:] -= cost+A.T@dual
        metrics = qp_residuals(zero,cost,A,low,high,primal,proposal)
        result["polish_metrics"] = metrics
        if residual_gate(metrics):
            dual = proposal
            original = metrics
    result.update(passed=bool(ans.success and residual_gate(original)),residuals=original,objective=float(cost@primal),all_original_rows_verified=True)
    return primal,dual,result
