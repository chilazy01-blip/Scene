"""Exact LP row separation: qualify against ALL rows and expanded dual variables."""
import time
import numpy as np
from scipy import sparse
from .linear_solver_ipm import solve_lp
from .globalization_gate import qp_residuals,residual_gate


def solve_with_separation(cost,A,low,high,witness,deadline,callback):
    A=A.tocsr();n=len(cost);groups=np.empty(A.shape[0],dtype=np.int32);by_support={}
    for row in range(A.shape[0]):
        key=tuple(A.indices[A.indptr[row]:A.indptr[row+1]])
        if key not in by_support:by_support[key]=len(by_support)
        groups[row]=by_support[key]
    row_norm=np.maximum(np.asarray(abs(A).max(axis=1).toarray()).ravel(),1e-12)
    value=A@witness;score=np.maximum(low-value,value-high)/row_norm
    def maxima(ids,scores):
        maximum=np.full(len(by_support),-np.inf);np.maximum.at(maximum,groups[ids],scores)
        candidates=ids[scores==maximum[groups[ids]]];_,first=np.unique(groups[candidates],return_index=True);return candidates[first]
    selected=set(map(int,maxima(np.arange(len(low)),score)));selected.update(range(A.shape[0]-n,A.shape[0]));history=[]
    callback(dict(status='grouped_original_rows',full_rows=A.shape[0],support_groups=len(by_support),initial_rows=len(selected)),None,None,None)
    for iteration in range(12):
        left=deadline-time.monotonic()-6
        if left<2:break
        ids=np.array(sorted(selected));primal,dual,info=solve_lp(cost,A[ids],low[ids],high[ids],min(12.,left));record=dict(iteration=iteration,selected_rows=len(ids),solver=info)
        if not info['passed']:
            history.append(record);callback(record,primal,None,ids);break
        full_dual=np.zeros(A.shape[0]);full_dual[ids]=dual;metrics=qp_residuals(sparse.csr_matrix((n,n)),cost,A,low,high,primal,full_dual);record['full_metrics']=metrics
        if residual_gate(metrics):
            history.append(record);callback(record,primal,full_dual,ids);return dict(passed=True,history=history,full_metrics=metrics,objective=float(cost@primal)),primal,full_dual
        val=A@primal;error=np.maximum(low-val,val-high);violated=np.flatnonzero(error>1e-8)
        if not len(violated):
            record['reason']='dual_certificate_not_qualified';history.append(record);callback(record,primal,full_dual,ids);break
        added=maxima(violated,error[violated]/row_norm);fresh=set(map(int,added))-selected;record['violated_full_rows']=len(violated);record['added_rows']=len(fresh);assert fresh
        selected.update(fresh);history.append(record);callback(record,primal,full_dual,ids)
    return dict(passed=False,history=history,reason='bounded_exact_row_separation_without_certificate'),None,None
