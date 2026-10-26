"""Bounded geometric repair and hard temporal projection; no convergence claim."""
import numpy as np
from scipy import sparse
import qpsolvers
from .fixed_body_discrete import feasibility_step


def geometric_repair(reference,lower,upper,jacobian,error,G,h,trust=.15):
    size=len(reference);H=np.zeros((size+1,size+1))
    H[:size,:size]=jacobian.T@jacobian+1e-5*np.eye(size);H[-1,-1]=1000.
    f=np.r_[jacobian.T@error,0.]
    rows=np.c_[G,-np.ones(len(h))]
    lo=np.r_[np.maximum(lower-reference,-trust),0.]
    hi=np.r_[np.minimum(upper-reference,trust),np.inf]
    delta=qpsolvers.solve_qp(H,f,rows,h,lb=lo,ub=hi,solver='quadprog')
    if delta is None:return None,None
    return reference+delta[:-1],float(delta[-1])


def temporal_projection(target,initial,lower,upper,time_limit=3.):
    n,j=target.shape;G=sparse.vstack([sparse.eye(n),-sparse.eye(n)],format='csr')
    result=np.empty_like(target);records=[]
    for k in range(j):
        q,info=feasibility_step(target[:,k:k+1],initial[k:k+1],np.zeros(1),
                 target[-1,k:k+1],lower[k:k+1],upper[k:k+1],G,
                 np.r_[target[:,k],-target[:,k]],trust=10.,stage_ends=[n],time_limit=time_limit)
        info['projection_error_rad']=info.pop('objective_m')
        info['scope']='single joint temporal projection; no collision qualification'
        records.append(info)
        if q is None:return None,records
        result[:,k]=q[:,0]
    return result,records
