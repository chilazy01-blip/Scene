"""Constraint generation with original full-row primal/dual certification.

Subset optima are never task certificates. A subset dual is expanded with zero
multipliers for omitted rows; acceptance additionally checks every original row.
"""
import time
import numpy as np
from scipy import sparse
from .glpk_model_r13 import Model
from .certified_sided_reduction_r4 import reduce_rows
from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds,callback=None):
    started=time.monotonic();deadline=started+seconds;A=A.tocsr();n=len(cost)
    B,lo,hi,mapping,reduction=reduce_rows(A,low,high)
    # Zero-cost variables can be fixed at a finite endpoint exactly when every
    # retained side is monotone toward that endpoint. No coefficient tolerance.
    csc=B.tocsc();fixed=np.zeros(n,dtype=bool);anchor=np.zeros(n);proof=[]
    for j in np.flatnonzero(cost==0):
        a,b=csc.indptr[j:j+2];r=csc.indices[a:b];v=csc.data[a:b]
        upper_ok=np.all((~np.isfinite(hi[r]))|(v<=0)) and np.all((~np.isfinite(lo[r]))|(v>=0))
        lower_ok=np.all((~np.isfinite(hi[r]))|(v>=0)) and np.all((~np.isfinite(lo[r]))|(v<=0))
        if upper_ok and np.isfinite(high[-n+j]):
            fixed[j]=True;anchor[j]=high[-n+j];proof.append(dict(column=int(j),endpoint='upper',value=float(anchor[j])))
        elif lower_ok and np.isfinite(low[-n+j]):
            fixed[j]=True;anchor[j]=low[-n+j];proof.append(dict(column=int(j),endpoint='lower',value=float(anchor[j])))
    free=np.flatnonzero(~fixed);shift=B@anchor;R=B[:,free].tocsr()
    reduction=dict(reduction,monotone_endpoint_eliminations=proof,remaining_variables=len(free))
    groups=np.empty(B.shape[0],dtype=np.int32);lookup={}
    for i in range(B.shape[0]):
        key=B.indices[B.indptr[i]:B.indptr[i+1]].tobytes()
        if key not in lookup:lookup[key]=len(lookup)
        groups[i]=lookup[key]
    norm=np.maximum(np.asarray(abs(B).max(axis=1).toarray()).ravel(),1e-12)
    def maxima(ids,scores):
        best=np.full(len(lookup),-np.inf);np.maximum.at(best,groups[ids],scores)
        eligible=ids[scores==best[groups[ids]]];_,first=np.unique(groups[eligible],return_index=True)
        return eligible[first]
    # Constraint selection uses original physical units. All original rows stay
    # in the acceptance certificate. No claim of exact redundancy for unselected
    # rows; any failed full-row certificate is rejected, independent of selection.
    ls=abs(mapping['lower_owner'][:,1]);us=abs(mapping['upper_owner'][:,1])
    def original_violation(values):return np.maximum((lo-values)/ls,(values-hi)/us)
    rr=np.repeat(np.arange(B.shape[0]),np.diff(B.indptr));vv=B.data;cc=B.indices
    mn=np.bincount(rr,weights=vv*np.where(vv>0,low[-n:][cc],high[-n:][cc]),minlength=B.shape[0])
    mx=np.bincount(rr,weights=vv*np.where(vv>0,high[-n:][cc],low[-n:][cc]),minlength=B.shape[0])
    # Infinite unavailable sides contribute -inf, not NaN, to seed scores.
    with np.errstate(invalid='ignore'):
        possible_lower=np.where(np.isfinite(lo),(lo-mn)/ls,-np.inf)
        possible_upper=np.where(np.isfinite(hi),(mx-hi)/us,-np.inf)
    eligible=np.flatnonzero(np.maximum(possible_lower,possible_upper)>1e-10)
    center=np.clip(np.zeros(n),low[-n:],high[-n:]);values=B@center;all_ids=np.arange(B.shape[0])
    selected=set(map(int,maxima(eligible,original_violation(values)[eligible])))
    reduction=dict(reduction,support_groups=len(lookup),initial_rows=len(selected),selection='support-diverse subset generation in original units; original full-row gates unchanged',seed_eligible_rows=len(eligible),seed_omitted_rows=B.shape[0]-len(eligible))
    if callback:callback(reduction)
    history=[];last_x=last_y=None;zero=sparse.csr_matrix((n,n))
    model=Model(cost[free],low[-n:][free],high[-n:][free]);ids=np.asarray(sorted(selected),dtype=np.int32)
    model.add(R[ids],lo[ids]-shift[ids],hi[ids]-shift[ids])
    try:
        for iteration in range(30):
            remaining=deadline-time.monotonic()-2
            if remaining<=.5:break
            sol,rowdual,coldual,native=model.solve(min(20.,remaining))
            record=dict(iteration=iteration,selected_rows=len(ids),status='Optimal' if native['optimal'] else 'GLPK nonoptimal',status_code=0 if native['optimal'] else 4,backend=native)
            x=anchor.copy();x[free]=sol;dy=np.zeros(B.shape[0]);dy[ids]=-rowdual
            owner=np.where((dy>=0)[:,None],mapping['upper_owner'],mapping['lower_owner'])
            y=np.zeros(A.shape[0]);np.add.at(y,owner[:,0].astype(int),dy*owner[:,1]);y[-n+free]=-coldual
            y[-n+np.flatnonzero(fixed)]=-(cost+A.T@y)[fixed]
            metrics=qp_residuals(zero,cost,A,low,high,x,y);record['full_original_metrics']=metrics
            if not residual_gate(metrics):
                proposal=y.copy();proposal[-n:]-=cost+A.T@y;polished=qp_residuals(zero,cost,A,low,high,x,proposal);record['polish_metrics']=polished
                if residual_gate(polished):y,metrics=proposal,polished
            last_x,last_y=x,y
            if native['optimal'] and residual_gate(metrics):
                history.append(record);print('exchange_iteration',record,flush=True)
                return x,y,dict(passed=True,status='GLPK subset optimum with original full-row certificate',status_code=0,seconds=time.monotonic()-started,
                    reduction=reduction,history=history,residuals=metrics,objective=float(cost@x),all_original_rows_verified=True,
                    numerical_backend='glpk_incremental_exact_fallback_full_certificate_r13')
            if not native['optimal']:
                history.append(record);print('exchange_iteration',record,flush=True);break
            violation=original_violation(B@x);violated=np.flatnonzero(violation>1e-9)
            fresh=set(map(int,maxima(violated,violation[violated])))-selected if len(violated) else set()
            absent=np.asarray([i for i in violated if int(i) not in selected],dtype=int)
            if len(absent):
                k=min(512,len(absent));fresh.update(map(int,absent[np.argpartition(violation[absent],-k)[-k:]]))
            record.update(violated_reduced_rows=len(violated),added_rows=len(fresh));history.append(record);print('exchange_iteration',record,flush=True)
            if not fresh:break
            add=np.asarray(sorted(fresh),dtype=np.int32);model.add(R[add],lo[add]-shift[add],hi[add]-shift[add]);ids=np.r_[ids,add];selected.update(fresh)
        return last_x,last_y,dict(selected_rows=sorted(selected),passed=False,status='GLPK without original certificate',status_code=4,
            seconds=time.monotonic()-started,reduction=reduction,history=history,numerical_backend='glpk_incremental_exact_fallback_full_certificate_r13')
    finally:model.close()
