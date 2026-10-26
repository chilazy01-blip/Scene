"""Audited linear subproblems on every original row, with explicit dual evidence."""
import time
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds):
    A=A.tocsr();up=np.flatnonzero(np.isfinite(high));down=np.flatnonzero(np.isfinite(low))
    C=sparse.vstack([A[up],-A[down]],format='csr');b=np.r_[high[up],-low[down]]
    start=time.monotonic()
    ans=linprog(cost,A_ub=C,b_ub=b,bounds=[(None,None)]*len(cost),method='highs',options=dict(time_limit=max(.01,seconds),primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
    info=dict(status=ans.message,status_code=int(ans.status),iterations=int(ans.nit),seconds=time.monotonic()-start,rows=A.shape[0],variables=A.shape[1],objective=float(ans.fun) if ans.fun is not None else None,passed=False)
    dual=None
    if ans.x is not None and ans.ineqlin.marginals is not None:
        dual=np.zeros(A.shape[0]);np.add.at(dual,up,-ans.ineqlin.marginals[:len(up)]);np.add.at(dual,down,ans.ineqlin.marginals[len(up):])
        info['residuals']=qp_residuals(sparse.csr_matrix((len(cost),len(cost))),cost,A,low,high,ans.x,dual)
        info['passed']=bool(ans.success and residual_gate(info['residuals']))
    return ans.x,dual,info
