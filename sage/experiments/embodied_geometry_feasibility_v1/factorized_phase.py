"""Exact component decomposition of the declared fixed-body linear model."""
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from .fixed_body_discrete import feasibility_step


def solve(anchor,initial,velocity,final,lower,upper,G,h,trust=.15,phase_trust=0.,
          dt=.02,terminal_ticks=25,time_limit=25.,stage_ends=None,phase_ends=None):
    del phase_trust,phase_ends
    n,width=anchor.shape;j=width-1;coo=G.tocoo();arm=coo.col%width<j
    structure=sparse.coo_matrix((np.ones(np.count_nonzero(arm)),
             (coo.row[arm],coo.col[arm]%width)),shape=(G.shape[0],j)).tocsr()
    structure.data[:]=1.;graph=structure.T@structure
    count,labels=connected_components(graph,directed=False)
    phase=np.zeros_like(anchor);phase[:,-1]=anchor[:,-1];rhs=h-G@phase.ravel()
    constant=np.asarray(structure.getnnz(axis=1)).ravel()==0
    constant_bound=float(np.min(rhs[constant],initial=0.))
    solution=anchor.copy();details=[]
    for group in range(count):
        members=np.flatnonzero(labels==group)
        columns=(np.arange(n)[:,None]*width+members).ravel()
        block=G[:,columns];rows=np.asarray(block.getnnz(axis=1)).ravel()>0
        # A row must not involve any other component; never discard coupling.
        outside=np.flatnonzero(labels!=group)
        assert structure[rows][:,outside].nnz==0
        block=sparse.vstack([block[rows],sparse.csr_matrix((1,n*len(members)))],format='csr')
        bounds=np.r_[rhs[rows],constant_bound]
        x,info=feasibility_step(anchor[:,members],initial[members],velocity[members],
                   final[members],lower[members],upper[members],block,bounds,
                   trust=trust,dt=dt,terminal_ticks=terminal_ticks,time_limit=time_limit,stage_ends=stage_ends)
        details.append(dict(members=members.tolist(),solver=info))
        if x is None:return None,dict(status='component_not_solved',components=count,results=details)
        solution[:,members]=x
    objective=max(r['solver']['objective_m'] for r in details)
    residual=float(np.max(G@solution.ravel()-h,initial=0.))
    assert residual<=objective+2e-7
    return solution,dict(status='components_solved',components=count,results=details,
                         objective_m=objective,full_geometry_residual_m=residual,
                         fixed_body_phase=True,all_cross_component_rows_absent=True)
