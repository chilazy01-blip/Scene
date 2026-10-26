"""Constraint generation with original full-row primal/dual certification.

Subset optima are never task certificates. A subset dual is expanded with zero
multipliers for omitted rows; acceptance additionally checks every original row.
"""
import time
import numpy as np
from scipy import sparse
from scipy.optimize._highspy import _core as hc
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
    eligible=np.flatnonzero(np.maximum((lo-mn)/ls,(mx-hi)/us)>1e-10)
    center=np.clip(np.zeros(n),low[-n:],high[-n:]);values=B@center;all_ids=np.arange(B.shape[0])
    selected=set(map(int,maxima(eligible,original_violation(values)[eligible])))
    reduction=dict(reduction,support_groups=len(lookup),initial_rows=len(selected),selection='support-diverse subset generation in original units; original full-row gates unchanged',seed_eligible_rows=len(eligible),seed_omitted_rows=B.shape[0]-len(eligible))
    if callback:callback(reduction)
    history=[];last_x=last_y=None;zero=sparse.csr_matrix((n,n))
    h=hc._Highs()
    options=dict(solver='simplex',simplex_strategy=1,presolve='on',parallel='off',threads=1,
                 primal_feasibility_tolerance=1e-9,dual_feasibility_tolerance=1e-9,
                 small_matrix_value=1e-12,output_flag=False)
    for key,value in options.items():
        if h.setOptionValue(key,value)!=hc.HighsStatus.kOk:raise RuntimeError('native_option_rejected:'+key)
    native=lambda v:np.where(np.isposinf(v),hc.kHighsInf,np.where(np.isneginf(v),-hc.kHighsInf,v))
    ids=np.asarray(sorted(selected),dtype=np.int32);C=R[ids].tocsc();nf=len(free)
    lp=hc.HighsLp();lp.num_col_=nf;lp.num_row_=len(ids)
    lp.col_cost_=cost[free];lp.col_lower_=native(low[-n:][free]);lp.col_upper_=native(high[-n:][free])
    lp.row_lower_=native(lo[ids]-shift[ids]);lp.row_upper_=native(hi[ids]-shift[ids])
    lp.a_matrix_.num_col_=nf;lp.a_matrix_.num_row_=len(ids);lp.a_matrix_.format_=hc.MatrixFormat.kColwise
    lp.a_matrix_.start_=C.indptr;lp.a_matrix_.index_=C.indices;lp.a_matrix_.value_=C.data
    if h.passModel(lp)==hc.HighsStatus.kError:raise RuntimeError('native_model_rejected')
    reduction=dict(reduction,incremental_basis_retained=True,new_rows_batch_limit=512)
    for iteration in range(40):
        remaining=deadline-time.monotonic()-2
        if remaining<=.5:break
        h.setOptionValue('time_limit',h.getRunTime()+remaining)
        t=time.monotonic();run_status=h.run();status=h.getModelStatus();info=h.getInfo();ans=h.getSolution()
        optimal=status==hc.HighsModelStatus.kOptimal
        record=dict(iteration=iteration,selected_rows=len(ids),seconds=time.monotonic()-t,status_code=0 if optimal else 4,
                    status=h.modelStatusToString(status),iterations=int(info.simplex_iteration_count),
                    value_valid=bool(ans.value_valid),dual_valid=bool(ans.dual_valid),
                    native_primal_error=float(info.max_primal_infeasibility),native_dual_error=float(info.max_dual_infeasibility))
        if not ans.value_valid or not ans.dual_valid:
            history.append(record);print('exchange_iteration',record,flush=True);break
        x=anchor.copy();x[free]=np.asarray(ans.col_value);dy=np.zeros(B.shape[0]);dy[ids]=-np.asarray(ans.row_dual)
        owner=np.where((dy>=0)[:,None],mapping['upper_owner'],mapping['lower_owner'])
        y=np.zeros(A.shape[0]);np.add.at(y,owner[:,0].astype(int),dy*owner[:,1]);y[-n+free]=-np.asarray(ans.col_dual)
        y[-n+np.flatnonzero(fixed)]=-(cost+A.T@y)[fixed]
        metrics=qp_residuals(zero,cost,A,low,high,x,y);record['full_original_metrics']=metrics
        if not residual_gate(metrics):
            proposal=y.copy();proposal[-n:]-=cost+A.T@y;polished=qp_residuals(zero,cost,A,low,high,x,proposal);record['polish_metrics']=polished
            if residual_gate(polished):y,metrics=proposal,polished
        last_x,last_y=x,y
        if optimal and residual_gate(metrics):
            history.append(record);print('exchange_iteration',record,flush=True)
            return x,y,dict(passed=True,status='Incremental subset optimum with original full-row certificate',status_code=0,seconds=time.monotonic()-started,
                reduction=reduction,history=history,residuals=metrics,objective=float(cost@x),all_original_rows_verified=True,
                numerical_backend='original_unit_incremental_dual_simplex_full_certificate_r10')
        if not optimal:
            history.append(record);print('exchange_iteration',record,flush=True);break
        violation=original_violation(B@x);violated=np.flatnonzero(violation>1e-9)
        fresh=set(map(int,maxima(violated,violation[violated])))-selected if len(violated) else set()
        absent=np.asarray([i for i in violated if int(i) not in selected],dtype=int)
        if len(absent):
            k=min(512,len(absent));fresh.update(map(int,absent[np.argpartition(violation[absent],-k)[-k:]]))
        record.update(violated_reduced_rows=len(violated),added_rows=len(fresh));history.append(record);print('exchange_iteration',record,flush=True)
        if not fresh:break
        add=np.asarray(sorted(fresh),dtype=np.int32);C=R[add].tocsr()
        added=h.addRows(len(add),native(lo[add]-shift[add]),native(hi[add]-shift[add]),C.nnz,C.indptr,C.indices,C.data)
        if added==hc.HighsStatus.kError:raise RuntimeError('native_add_rows_failed')
        ids=np.r_[ids,add];selected.update(fresh)
    return last_x,last_y,dict(selected_rows=sorted(selected),passed=False,status='Incremental basis without original certificate',status_code=4,
        seconds=time.monotonic()-started,reduction=reduction,history=history,numerical_backend='original_unit_incremental_dual_simplex_full_certificate_r10')
