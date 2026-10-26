"""Whole-phase L-infinity joint projection with sparse finite differences.

Geometry is deliberately left to an independent audit; this solver establishes
only native joint ranges, discrete speed/acceleration and fixed endpoint holds.
"""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog


def project(desired, initial, lower, upper, speed=.35, acceleration=.5, dt=.02, terminal_ticks=25):
    desired=np.asarray(desired,dtype=float);initial=np.asarray(initial,dtype=float);lower=np.asarray(lower,dtype=float);upper=np.asarray(upper,dtype=float)
    if desired.ndim!=2 or not np.isfinite(desired).all() or any(x.shape!=(desired.shape[1],) or not np.isfinite(x).all() for x in [initial,lower,upper]) or np.any(lower>upper) or np.any(initial<lower) or np.any(initial>upper) or min(speed,acceleration,dt)<=0 or not isinstance(terminal_ticks,int) or not 2<=terminal_ticks<desired.shape[0]:raise ValueError('projection_input')
    n,joints=desired.shape;identity=sparse.eye(n,format='csr');D1=sparse.diags([np.ones(n),-np.ones(n-1)],[0,-1],shape=(n,n),format='csr');D2=D1@D1
    zeros=sparse.csr_matrix((n,1));ones=sparse.csr_matrix(-np.ones((n,1)))
    A=sparse.vstack([sparse.hstack([identity,ones]),sparse.hstack([-identity,ones]),sparse.hstack([D1,zeros]),sparse.hstack([-D1,zeros]),sparse.hstack([D2,zeros]),sparse.hstack([-D2,zeros])],format='csr')
    c=np.r_[np.zeros(n),1.];result=np.empty_like(desired);records=[]
    for j in range(joints):
        b1=np.zeros(n);b1[0]=-initial[j];b2=np.zeros(n);b2[0]=-initial[j];b2[1]=initial[j]
        b=np.r_[desired[:,j],-desired[:,j],np.full(n,speed*dt)-b1,np.full(n,speed*dt)+b1,np.full(n,acceleration*dt*dt)-b2,np.full(n,acceleration*dt*dt)+b2]
        bounds=[(float(lower[j]),float(upper[j]))]*(n-terminal_ticks)+[(float(desired[-1,j]),float(desired[-1,j]))]*terminal_ticks+[(0,None)]
        lp=linprog(c,A_ub=A,b_ub=b,bounds=bounds,method='highs',options={'presolve':True,'dual_feasibility_tolerance':1e-8,'primal_feasibility_tolerance':1e-8,'time_limit':8.})
        records.append(dict(joint=j,status=int(lp.status),success=bool(lp.success),message=lp.message,max_deviation_rad=float(lp.fun) if lp.success else None))
        if not lp.success:return None,records
        result[:,j]=lp.x[:-1]
    return result,records
