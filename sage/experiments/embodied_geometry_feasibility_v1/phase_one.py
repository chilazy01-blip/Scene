"""Full discrete phase feasibility QP; soft geometry never grants admission."""
import numpy as np
from scipy import sparse
import osqp


def operators(n, joints, initial, initial_velocity, dt=.02):
    D = sparse.diags([np.ones(n), -np.ones(n-1)], [0, -1], shape=(n,n))
    first = sparse.kron(D, sparse.eye(joints), format='csr')
    second = first @ first
    b1 = np.zeros(n*joints); b1[:joints] = -initial
    b2 = b1.copy(); b2[:joints] -= dt*initial_velocity
    b2[joints:2*joints] = initial
    return first, second, b1, b2


def feasibility_step(anchor, initial, initial_velocity, final, lower, upper,
                     geometry, bound, trust=.15, dt=.02, terminal_ticks=25,
                     speed=.35, acceleration=.5, time_limit=25.):
    """Minimize squared positive geometric residual under hard kinematics.

    Geometry rows are in meters; slacks are normalized by 6 mm. The full
    discrete parameterization is retained. Native stopping is the entire
    straight joint-space uniform ramp, equivalent to checking its endpoints.
    This does NOT establish collision clearance along that ramp.
    """
    anchor = np.asarray(anchor); n,joints = anchor.shape; size=n*joints
    I=sparse.eye(size,format='csr')
    D1,D2,b1,b2=operators(n,joints,initial,initial_velocity,dt)
    flat=anchor.ravel(); v0=D1@flat+b1; a0=D2@flat+b2
    # Current point plus future ramp displacement (17.5 intervals at dt=.02).
    future = (speed/acceleration)/(2*dt)
    stop=I+future*D1; stop0=stop@flat+future*b1
    lo=np.maximum(np.tile(lower,n)-flat,-trust)
    hi=np.minimum(np.tile(upper,n)-flat,trust)
    lo[-terminal_ticks*joints:]=np.tile(final,terminal_ticks)-flat[-terminal_ticks*joints:]
    hi[-terminal_ticks*joints:]=lo[-terminal_ticks*joints:]
    hard=sparse.vstack([I,D1,D2,stop],format='csr')
    low=np.r_[lo,-speed*dt-v0,-acceleration*dt*dt-a0,np.tile(lower,n)-stop0]
    high=np.r_[hi,speed*dt-v0,acceleration*dt*dt-a0,np.tile(upper,n)-stop0]
    g=geometry/.006; h=(bound-geometry@flat)/.006; rows=len(h)
    A=sparse.vstack([
        sparse.hstack([hard,sparse.csr_matrix((hard.shape[0],rows))]),
        sparse.hstack([g,-sparse.eye(rows)]),
        sparse.hstack([sparse.csr_matrix((rows,size)),sparse.eye(rows)])],format='csc')
    l=np.r_[low,np.full(rows,-np.inf),np.zeros(rows)]
    u=np.r_[high,h,np.full(rows,np.inf)]
    P=sparse.diags(np.r_[np.full(size,2e-4),np.full(rows,2.)],format='csc')
    solver=osqp.OSQP()
    solver.setup(P=P,q=np.zeros(size+rows),A=A,l=l,u=u,verbose=False,
                 eps_abs=1e-8,eps_rel=1e-8,max_iter=30000,time_limit=time_limit,
                 polishing=True,adaptive_rho=True)
    solver.warm_start(x=np.r_[np.zeros(size),np.maximum(-h,0.)])
    result=solver.solve(); info=result.info
    record=dict(status=info.status,status_val=int(info.status_val),iterations=int(info.iter),
                run_time=float(info.run_time),variables=size+rows,inequalities=A.shape[0],
                nonzeros=A.nnz,objective=float(info.obj_val),geometry_rows=rows,
                solver_version=osqp.__version__,full_discrete_parameterization=True)
    if result.x is None or not np.isfinite(result.x).all():return None,record
    delta=result.x[:size]; actual=hard@delta
    hard_excess=max(0.,float(np.max(low-actual)),float(np.max(actual-high)))
    record.update(hard_constraint_excess=hard_excess,
                  max_linear_geometry_violation_m=float(np.maximum(geometry@(flat+delta)-bound,0.).max(initial=0)))
    # Solver status alone is insufficient; exact saved path is also rechecked.
    if hard_excess>2e-8:return None,record
    return (flat+delta).reshape(n,joints),record
