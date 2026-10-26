"""Sparse L-infinity geometry phase I with original hard kinematic bounds."""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .phase_one import operators
from .discrete_stop import reserve


def feasibility_step(anchor, initial, initial_velocity, final, lower, upper,
                     geometry, bound, trust=.15, dt=.02, terminal_ticks=25,
                     speed=.35, acceleration=.5, time_limit=25., stage_ends=None):
    n,joints=anchor.shape;size=n*joints;flat=anchor.ravel()
    I=sparse.eye(size,format='csr');D1,D2,b1,b2=operators(n,joints,initial,initial_velocity,dt)
    v0=D1@flat+b1;a0=D2@flat+b2;future,offset=reserve(speed,acceleration,dt)
    speed_bound=np.full((n,joints),speed*dt)
    for endpoint in stage_ends:speed_bound[int(endpoint)-25:int(endpoint)]=.08*dt
    speed_bound=speed_bound.ravel()
    stop=I+future*D1;stop0=stop@flat+future*b1
    lo=np.maximum(np.tile(lower,n)-flat,-trust);hi=np.minimum(np.tile(upper,n)-flat,trust)
    lo[-terminal_ticks*joints:]=np.tile(final,terminal_ticks)-flat[-terminal_ticks*joints:]
    hi[-terminal_ticks*joints:]=lo[-terminal_ticks*joints:]
    hard=sparse.vstack([D1,-D1,D2,-D2,stop,-stop],format='csr')
    hard_h=np.r_[speed_bound-v0,speed_bound+v0,acceleration*dt*dt-a0,acceleration*dt*dt+a0,np.tile(upper,n)+offset-stop0,stop0-np.tile(lower,n)+offset]
    h=bound-geometry@flat
    A=sparse.vstack([sparse.hstack([hard,sparse.csr_matrix((hard.shape[0],1))]),
                    sparse.hstack([geometry,sparse.csr_matrix(-np.ones((len(h),1)))])],format='csr')
    bounds=np.c_[np.r_[lo,0.],np.r_[hi,np.inf]]
    result=linprog(np.r_[np.zeros(size),1.],A_ub=A,b_ub=np.r_[hard_h,h],bounds=bounds,
                   method='highs-ipm',options=dict(time_limit=time_limit,presolve=True,
                     primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9,ipm_optimality_tolerance=1e-10))
    info=dict(status=result.message,status_val=int(result.status),iterations=int(result.nit),
              variables=size+1,inequalities=A.shape[0],nonzeros=A.nnz,
              solver='scipy_highs_ipm',full_discrete_parameterization=True,
              objective_m=float(result.fun) if result.success else None)
    if not result.success:return None,info
    delta=result.x[:-1];excess=max(0.,float(np.max(hard@delta-hard_h)),float(np.max(lo-delta)),float(np.max(delta-hi)))
    info.update(hard_constraint_excess=excess,max_linear_geometry_violation_m=float(np.maximum(geometry@(flat+delta)-bound,0.).max(initial=0)))
    if excess>2e-8:return None,info
    return (flat+delta).reshape(n,joints),info
