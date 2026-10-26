"""Same LP and full-row certificate; interior point plus equivalent native bounds."""
import time
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds):
    A=A.tocsr();n=len(cost);assert (A[-n:]-sparse.eye(n,format='csr')).nnz==0
    block=A[:-n];lo=low[:-n];hi=high[:-n];up=np.flatnonzero(np.isfinite(hi));down=np.flatnonzero(np.isfinite(lo))
    C=sparse.vstack([block[up],-block[down]],format='csr');b=np.r_[hi[up],-lo[down]];started=time.monotonic()
    ans=linprog(cost,A_ub=C,b_ub=b,bounds=list(zip(low[-n:],high[-n:])),method='highs-ipm',options=dict(time_limit=max(.01,seconds),presolve=True,ipm_optimality_tolerance=1e-10,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
    info=dict(status=ans.message,status_code=int(ans.status),iterations=int(ans.nit),seconds=time.monotonic()-started,rows=A.shape[0],variables=A.shape[1],objective=float(ans.fun) if ans.fun is not None else None,passed=False,numerical_backend='highs_ipm_native_bounds')
    dual=None
    if ans.x is not None and ans.ineqlin.marginals is not None:
        dual=np.zeros(A.shape[0]);np.add.at(dual,up,-ans.ineqlin.marginals[:len(up)]);np.add.at(dual,down,ans.ineqlin.marginals[len(up):]);dual[-n:]=-ans.lower.marginals-ans.upper.marginals
        info['residuals']=qp_residuals(sparse.csr_matrix((n,n)),cost,A,low,high,ans.x,dual);info['passed']=bool(ans.success and residual_gate(info['residuals']))
    return ans.x,dual,info
