"""Restore a QP primal against every original inequality; never accept a label alone."""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog

def restore(A,lower,upper,primal,time_limit=10.):
    up=np.isfinite(upper);low=np.isfinite(lower);value=A@primal;n=len(primal)
    C=sparse.vstack([A[up],-A[low]],format='csr');bound=np.r_[upper[up]-value[up],value[low]-lower[low]]
    identity=sparse.eye(n,format='csr')
    matrix=sparse.vstack([sparse.hstack([C,sparse.csr_matrix((C.shape[0],1))]),sparse.hstack([identity,-np.ones((n,1))]),sparse.hstack([-identity,-np.ones((n,1))])],format='csr')
    result=linprog(np.r_[np.zeros(n),1.],A_ub=matrix,b_ub=np.r_[bound,np.zeros(2*n)],bounds=[(None,None)]*n+[(0.,None)],method='highs',options=dict(time_limit=time_limit,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
    info=dict(status=result.message,status_val=int(result.status),iterations=int(result.nit),correction_inf=float(result.fun) if result.success else None)
    if not result.success:return None,info
    x=primal+result.x[:-1];residual=max(0.,float(np.max(lower-A@x)),float(np.max(A@x-upper)));info['original_row_residual']=residual
    return (x if residual<=2e-8 else None),info
