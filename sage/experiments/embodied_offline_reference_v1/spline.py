"""Cubic arm-reference subspace, exact checks at every original control tick.

Hands stay at the constant carry command. This is a restricted candidate
family, not an equivalent reformulation of the unrestricted reference LP.
"""
import numpy as np
from scipy import sparse
from scipy.interpolate import BSpline
from scipy.optimize import linprog


def project_coupled(desired,initial,lower,upper,extra_G,extra_h,anchor,trust=.35,speed=.35,acceleration=.5,dt=.02,terminal_ticks=25,fixed_columns=None):
    desired=np.asarray(desired);n,joints=desired.shape;size=n*joints;fixed=np.asarray(fixed_columns,dtype=bool);free=np.flatnonzero(~fixed)
    if fixed.shape!=(joints,) or np.max(abs(desired[:,fixed]-initial[fixed]),initial=0.)>1e-10:raise ValueError('spline_requires_constant_fixed_hands')
    end=(n-terminal_ticks+1)*dt;x=np.minimum((np.arange(n)+1)*dt,end);knots=np.r_[np.zeros(4),np.linspace(0,end,41)[1:-1],np.full(4,end)];basis=sparse.csr_matrix(BSpline.design_matrix(x,knots,3));nc=basis.shape[1]
    mapping=sparse.csr_matrix((np.ones(len(free)),(free,np.arange(len(free)))),shape=(joints,len(free)));C=sparse.kron(basis,mapping,format='csr');base=np.zeros((n,joints));base[:,fixed]=desired[:,fixed];base=base.ravel();coeffs=nc*len(free)
    I=sparse.eye(size,format='csr');D=sparse.diags([np.ones(n),-np.ones(n-1)],[0,-1],shape=(n,n));D1=sparse.kron(D,sparse.eye(joints),format='csr');D2=D1@D1;b1=np.zeros(size);b1[:joints]=-initial;b2=b1.copy();b2[joints:2*joints]=initial
    lo=np.maximum(lower,anchor-trust).ravel();hi=np.minimum(upper,anchor+trust).ravel();lo[-terminal_ticks*joints:]=np.tile(desired[-1],terminal_ticks);hi[-terminal_ticks*joints:]=lo[-terminal_ticks*joints:]
    Aq=sparse.vstack([I,-I,D1,-D1,D2,-D2,extra_G,I,-I],format='csr');rhs=np.r_[desired.ravel(),-desired.ravel(),np.full(size,speed*dt)-b1,np.full(size,speed*dt)+b1,np.full(size,acceleration*dt*dt)-b2,np.full(size,acceleration*dt*dt)+b2,extra_h,hi,-lo]
    tau=np.r_[-np.ones(2*size),np.zeros(len(rhs)-2*size)];A=sparse.hstack([Aq@C,sparse.csr_matrix(tau[:,None])],format='csr');rhs-=Aq@base
    row_nonzero=np.diff(A.indptr)>0
    if np.any(rhs[~row_nonzero]<-1e-8):return None,dict(status=2,success=False,message='constant subspace inequality violated',variables=coeffs+1,inequalities=len(rhs),nonzeros=A.nnz,max_deviation_rad=None)
    A=A[row_nonzero];rhs=rhs[row_nonzero];clo=np.tile(lower[free],(nc,1));chi=np.tile(upper[free],(nc,1));clo[:3]=initial[free];chi[:3]=initial[free];clo[-3:]=desired[-1,free];chi[-3:]=desired[-1,free]
    lp=linprog(np.r_[np.zeros(coeffs),1.],A_ub=A,b_ub=rhs,bounds=np.c_[np.r_[clo.ravel(),0.],np.r_[chi.ravel(),np.inf]],method='highs-ipm',options={'presolve':True,'primal_feasibility_tolerance':1e-8,'dual_feasibility_tolerance':1e-8,'time_limit':30.})
    info=dict(status=int(lp.status),success=bool(lp.success),message=lp.message,variables=coeffs+1,original_reference_variables=size+1,inequalities=A.shape[0],nonzeros=A.nnz,basis_coefficients_per_arm_joint=nc,fixed_hand_columns=int(fixed.sum()),max_deviation_rad=float(lp.fun) if lp.success else None)
    return ((C@lp.x[:-1]+base).reshape(n,joints) if lp.success else None),info
