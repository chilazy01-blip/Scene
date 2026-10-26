"""Sparse whole-phase reference projection with caller-supplied geometric rows."""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog


def project_coupled(desired, initial, lower, upper, extra_G, extra_h, anchor, trust=.35, speed=.35, acceleration=.5, dt=.02, terminal_ticks=25):
    desired=np.asarray(desired);n,joints=desired.shape;size=n*joints;I=sparse.eye(size,format='csr');D=sparse.diags([np.ones(n),-np.ones(n-1)],[0,-1],shape=(n,n));D1=sparse.kron(D,sparse.eye(joints),format='csr');D2=D1@D1
    zero=sparse.csr_matrix((size,1));minus=sparse.csr_matrix(-np.ones((size,1)));blocks=[sparse.hstack([I,minus]),sparse.hstack([-I,minus]),sparse.hstack([D1,zero]),sparse.hstack([-D1,zero]),sparse.hstack([D2,zero]),sparse.hstack([-D2,zero]),sparse.hstack([extra_G,sparse.csr_matrix((len(extra_h),1))])]
    A=sparse.vstack(blocks,format='csr');b1=np.zeros(size);b1[:joints]=-initial;b2=b1.copy();b2[joints:2*joints]=initial
    b=np.r_[desired.ravel(),-desired.ravel(),np.full(size,speed*dt)-b1,np.full(size,speed*dt)+b1,np.full(size,acceleration*dt*dt)-b2,np.full(size,acceleration*dt*dt)+b2,extra_h]
    lo=np.maximum(lower,anchor-trust).ravel();hi=np.minimum(upper,anchor+trust).ravel();lo[-terminal_ticks*joints:]=np.tile(desired[-1],terminal_ticks);hi[-terminal_ticks*joints:]=lo[-terminal_ticks*joints:]
    objective=np.r_[np.zeros(size),1.];bounds=np.c_[np.r_[lo,0.],np.r_[hi,np.inf]]
    lp=linprog(objective,A_ub=A,b_ub=b,bounds=bounds,method='highs-ipm',options={'presolve':True,'primal_feasibility_tolerance':1e-8,'dual_feasibility_tolerance':1e-8,'time_limit':30.})
    info=dict(status=int(lp.status),success=bool(lp.success),message=lp.message,variables=size+1,inequalities=A.shape[0],nonzeros=A.nnz,max_deviation_rad=float(lp.fun) if lp.success else None)
    return (lp.x[:-1].reshape(n,joints) if lp.success else None),info
