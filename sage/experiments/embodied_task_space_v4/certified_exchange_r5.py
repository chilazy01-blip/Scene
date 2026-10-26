"""Constraint generation with original full-row primal/dual certification.

Subset optima are never task certificates. A subset dual is expanded with zero
multipliers for omitted rows; acceptance additionally checks every original row.
"""
import time
import numpy as np
from scipy import sparse
from scipy.optimize import linprog
from .certified_sided_reduction_r4 import reduce_rows
from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds,callback=None):
    started=time.monotonic();deadline=started+seconds;A=A.tocsr();n=len(cost)
    B,lo,hi,mapping,reduction=reduce_rows(A,low,high)
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
    center=np.clip(np.zeros(n),low[-n:],high[-n:]);values=B@center;all_ids=np.arange(B.shape[0])
    selected=set(map(int,maxima(all_ids,np.maximum(lo-values,values-hi)/norm)))
    reduction=dict(reduction,support_groups=len(lookup),initial_rows=len(selected),selection='support-diverse exact constraint generation, plus largest original violations')
    if callback:callback(reduction)
    history=[];last_x=last_y=None;zero=sparse.csr_matrix((n,n))
    for iteration in range(12):
        remaining=deadline-time.monotonic()-2
        if remaining<=.5:break
        ids=np.asarray(sorted(selected));up=np.flatnonzero(np.isfinite(hi[ids]));down=np.flatnonzero(np.isfinite(lo[ids]))
        C=sparse.vstack([B[ids[up]],-B[ids[down]]],format='csr');rhs=np.r_[hi[ids[up]],-lo[ids[down]]]
        t=time.monotonic();ans=linprog(cost,A_ub=C,b_ub=rhs,bounds=list(zip(low[-n:],high[-n:])),method='highs-ipm',options=dict(time_limit=min(10.,remaining),presolve=True,ipm_optimality_tolerance=1e-10,primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9))
        record=dict(iteration=iteration,selected_rows=len(ids),seconds=time.monotonic()-t,status_code=int(ans.status),status=ans.message,iterations=int(ans.nit))
        if ans.x is None or ans.ineqlin.marginals is None:
            history.append(record);print('exchange_iteration',record,flush=True);break
        x=ans.x;dy=np.zeros(B.shape[0]);np.add.at(dy,ids[up],-ans.ineqlin.marginals[:len(up)]);np.add.at(dy,ids[down],ans.ineqlin.marginals[len(up):])
        owner=np.where((dy>=0)[:,None],mapping['upper_owner'],mapping['lower_owner']);y=np.zeros(A.shape[0]);np.add.at(y,owner[:,0].astype(int),dy*owner[:,1]);y[-n:]=-ans.lower.marginals-ans.upper.marginals
        metrics=qp_residuals(zero,cost,A,low,high,x,y);record['full_original_metrics']=metrics
        if not residual_gate(metrics):
            proposal=y.copy();proposal[-n:]-=cost+A.T@y;polished=qp_residuals(zero,cost,A,low,high,x,proposal);record['polish_metrics']=polished
            if residual_gate(polished):y,metrics=proposal,polished
        last_x,last_y=x,y
        if ans.success and residual_gate(metrics):
            history.append(record);print('exchange_iteration',record,flush=True)
            return x,y,dict(passed=True,status='Original full-row primal-dual certificate passed after subset optimum',status_code=0,seconds=time.monotonic()-started,reduction=reduction,history=history,residuals=metrics,objective=float(cost@x),all_original_rows_verified=True,numerical_backend='proved_sided_reduction_support_exchange_full_certificate_r5')
        values=B@x;violation=np.maximum(lo-values,values-hi);violated=np.flatnonzero(violation>1e-10)
        fresh=set(map(int,maxima(violated,violation[violated]/norm[violated])))-selected if len(violated) else set()
        # Add the largest remaining side violations as well, not just one per group.
        absent=np.asarray([i for i in violated if int(i) not in selected],dtype=int)
        if len(absent):
            k=min(4096,len(absent));top=absent[np.argpartition(violation[absent]/norm[absent],-k)[-k:]];fresh.update(map(int,top))
        record.update(violated_reduced_rows=len(violated),added_rows=len(fresh));history.append(record);print('exchange_iteration',record,flush=True)
        if not fresh:break
        selected.update(fresh)
    return last_x,last_y,dict(passed=False,status='Bounded constraint generation without original certificate',status_code=4,seconds=time.monotonic()-started,reduction=reduction,history=history,numerical_backend='proved_sided_reduction_support_exchange_full_certificate_r5')
