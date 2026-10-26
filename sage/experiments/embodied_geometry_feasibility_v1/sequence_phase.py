"""Full joint/time and monotone source-body phase LP; no path basis reduction."""
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .phase_one import operators
from .discrete_stop import reserve


def solve(anchor, initial, velocity, final, lower, upper, G, h, trust=.15,
          phase_trust=.6, dt=.02, terminal_ticks=25, time_limit=25., stage_ends=None, phase_ends=None):
    n,width=anchor.shape;j=width-1;size=n*width;flat=anchor.ravel()
    select=sparse.kron(sparse.eye(n),sparse.csr_matrix(np.c_[np.eye(j),np.zeros(j)]),format='csr')
    pick=sparse.kron(sparse.eye(n),sparse.csr_matrix(np.r_[np.zeros(j),1.][None]),format='csr')
    I=sparse.eye(n*j,format='csr');D1,D2,b1,b2=operators(n,j,initial,velocity,dt)
    q=anchor[:,:j].ravel();v0=D1@q+b1;a0=D2@q+b2
    K,offset=reserve(dt=dt);stop=I+K*D1;stop0=stop@q+K*b1
    phase_D=sparse.diags([np.ones(n),-np.ones(n-1)],[0,-1],shape=(n,n),format='csr');phase0=phase_D@anchor[:,-1]
    hard=sparse.vstack([D1@select,-D1@select,D2@select,-D2@select,stop@select,-stop@select,phase_D@pick,-phase_D@pick],format='csr')
    speed_bounds=np.full((n,j),.35*dt)
    for endpoint in stage_ends:speed_bounds[int(endpoint)-25:int(endpoint)]=.08*dt
    speed_bounds=speed_bounds.ravel()
    hard_h=np.r_[speed_bounds-v0,speed_bounds+v0,.5*dt*dt-a0,.5*dt*dt+a0,np.tile(upper,n)+offset-stop0,stop0-np.tile(lower,n)+offset,dt-phase0,phase0]
    lower_all=np.tile(np.r_[lower,0.],(n,1));upper_all=np.tile(np.r_[upper,final[-1]],(n,1));previous=0;source_start=0.
    for endpoint,phase_end in zip(stage_ends,phase_ends):
        endpoint=int(endpoint);lower_all[previous:endpoint,-1]=source_start;upper_all[previous:endpoint,-1]=phase_end
        lower_all[endpoint-25:endpoint,-1]=phase_end;upper_all[endpoint-25:endpoint,-1]=phase_end
        previous=endpoint;source_start=phase_end
    trust_all=np.r_[np.full(j,trust),phase_trust]
    lo=np.maximum(lower_all-anchor,-trust_all).ravel();hi=np.minimum(upper_all-anchor,trust_all).ravel()
    lo[-terminal_ticks*width:]=(final-anchor[-terminal_ticks:]).ravel();hi[-terminal_ticks*width:]=lo[-terminal_ticks*width:]
    A=sparse.vstack([sparse.hstack([hard,sparse.csr_matrix((hard.shape[0],1))]),sparse.hstack([G,sparse.csr_matrix(-np.ones((len(h),1)))])],format='csr')
    rhs=np.r_[hard_h,h-G@flat]
    r=linprog(np.r_[np.zeros(size),1.],A_ub=A,b_ub=rhs,bounds=np.c_[np.r_[lo,0.],np.r_[hi,np.inf]],method='highs-ipm',options=dict(time_limit=time_limit,presolve=True,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9,ipm_optimality_tolerance=1e-10))
    info=dict(status=r.message,status_val=int(r.status),iterations=int(r.nit),variables=size+1,inequalities=A.shape[0],nonzeros=A.nnz,objective_m=float(r.fun) if r.success else None)
    if not r.success:return None,info
    delta=r.x[:-1];excess=max(0.,float(np.max(hard@delta-hard_h)),float(np.max(lo-delta)),float(np.max(delta-hi)));info['hard_excess']=excess
    return ((flat+delta).reshape(n,width) if excess<=2e-8 else None),info
