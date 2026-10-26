"""Nearest temporal reference in squared joint distance under hard bounds."""
import numpy as np
from scipy import sparse
import osqp
from .phase_one import operators
from .discrete_stop import reserve


def temporal_projection(target,initial,lower,upper,time_limit=3.,stage_ends=None,initial_velocity=None):
    n,j=target.shape;stage_ends=[n] if stage_ends is None else stage_ends
    initial_velocity=np.zeros(j) if initial_velocity is None else np.asarray(initial_velocity)
    result=np.empty_like(target);records=[];I=sparse.eye(n,format='csc');K,offset=reserve()
    for k in range(j):
        D1,D2,b1,b2=operators(n,1,initial[k:k+1],initial_velocity[k:k+1])
        stop=I+K*D1;lo=np.full(n,lower[k]);hi=np.full(n,upper[k]);lo[-25:]=target[-1,k];hi[-25:]=target[-1,k]
        vmax=np.full(n,.007)
        for endpoint in stage_ends:vmax[int(endpoint)-25:int(endpoint)]=.0016
        A=sparse.vstack([I,D1,D2,stop],format='csc')
        low=np.r_[lo,-vmax-b1,-.0002-b2,np.full(n,lower[k]-offset)-K*b1]
        high=np.r_[hi,vmax-b1,.0002-b2,np.full(n,upper[k]+offset)-K*b1]
        solver=osqp.OSQP();solver.setup(P=2*I,q=-2*target[:,k],A=A,l=low,u=high,verbose=False,
                    eps_abs=1e-9,eps_rel=1e-9,max_iter=100000,time_limit=time_limit,polishing=True)
        solver.warm_start(x=target[:,k]);r=solver.solve();info=dict(joint=k,status=r.info.status,iterations=int(r.info.iter),run_time=float(r.info.run_time),objective='squared_reference_distance')
        if r.x is None or not np.isfinite(r.x).all():records.append(info);return None,records
        observed=A@r.x;excess=max(0.,float(np.max(low-observed)),float(np.max(observed-high)))
        info.update(hard_excess=excess,squared_distance=float(np.sum((r.x-target[:,k])**2)));records.append(info)
        if excess>2e-8:return None,records
        result[:,k]=r.x
    return result,records
