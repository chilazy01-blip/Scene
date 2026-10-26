"""Numerical sensitivity of a sealed QP, with unchanged contact/endpoint rows.

This only changes its declared trust radius; it neither evaluates a robot path
nor admits a method. Source row layout is checked rather than assumed silently.
"""
import numpy as np
from scipy import sparse

def layout(A, low, high, old_radius):
    size=A.shape[1];n=size-107
    if n<=0 or not 0<old_radius<=.25:raise ValueError('unrecognized_problem')
    if A.shape[0]<size or not np.array_equal(A[-size:].toarray(),np.eye(size)):
        raise ValueError('missing_terminal_variable_bounds')
    lower=low[-size:][:n];upper=high[-size:][:n]
    fixed=(lower==0)&(upper==0);free=~fixed
    if not np.all(lower[free]==-old_radius) or not np.all(upper[free]==old_radius):
        raise ValueError('unexpected_trust_bounds')
    candidates=A[:,size-2].tocoo();selected=[]
    for row,value in zip(candidates.row,candidates.data):
        if value!=-1:continue
        j=A.indices[A.indptr[row]:A.indptr[row+1]];v=A.data[A.indptr[row]:A.indptr[row+1]]
        mask=j<n
        if len(j)!=2 or np.sum(mask)!=1 or abs(abs(v[mask][0])-1/old_radius)>1e-10:
            raise ValueError('unrecognized_step_norm_row')
        if not np.isneginf(low[row]) or high[row]!=0:raise ValueError('unexpected_step_norm_bound')
        selected.append((int(row),int(j[mask][0]),float(np.sign(v[mask][0]))))
    if len(selected)!=2*n or sorted((col,sign) for row,col,sign in selected)!=[(i,s) for i in range(n) for s in [-1.,1.]]:
        raise ValueError('incomplete_step_norm_rows')
    return dict(variables=n,fixed=np.flatnonzero(fixed),free=np.flatnonzero(free),norm_rows=selected)

def with_radius(A,low,high,old_radius,new_radius):
    if not np.isfinite(new_radius) or not 0<new_radius<=.25:raise ValueError('outside_original_trust_cap')
    plan=layout(A,low,high,old_radius);B=A.copy();lo=low.copy();hi=high.copy()
    for row,col,sign in plan['norm_rows']:
        start,end=B.indptr[row:row+2];offset=start+int(np.flatnonzero(B.indices[start:end]==col)[0]);B.data[offset]=sign/new_radius
    indices=A.shape[0]-A.shape[1]+plan['free'];lo[indices]=-new_radius;hi[indices]=new_radius
    return B,lo,hi,plan

def endpoint_models(A,high,n):
    models=[]
    for phase in range(15):
        c=A[:,n+60+2*phase].tocoo();rows=sorted(int(r) for r,v in zip(c.row,c.data) if v==-1)
        if len(rows)!=12:raise ValueError('palm_endpoint_row_count')
        pos,neg=rows[:6],rows[6:];J=A[pos,:n]*.006;error=.003-high[pos]*.006
        delta=(A[pos,:n]+A[neg,:n]);delta.eliminate_zeros()
        if delta.nnz or np.max(abs(high[pos]+high[neg]-1.))>1e-10:raise ValueError('endpoint_row_pair_mismatch')
        models.append((J,error))
    return models

def predict(models,primal,n):
    return [float(np.linalg.norm((error+J@primal[:n]).reshape(2,3),axis=1).max()) for J,error in models]
