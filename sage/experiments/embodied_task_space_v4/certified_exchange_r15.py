"""Constraint generation with original full-row primal/dual certification.

Subset optima are never task certificates. A subset dual is expanded with zero
multipliers for omitted rows; acceptance additionally checks every original row.
"""
import time
import numpy as np
from scipy import sparse
from .clarabel_face_r15 import linprog
from scipy import linalg
from .certified_sided_reduction_r4 import reduce_rows
from sage.experiments.embodied_task_space_v3.globalization_gate import qp_residuals,residual_gate


def solve_lp(cost,A,low,high,seconds,callback=None,coordinate_face=None,reference=None):
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
    free=np.flatnonzero(~fixed)
    if reference is not None:
        reference=np.asarray(reference,dtype=float);assert reference.shape==(n,) and np.isfinite(reference).all()
        change=(cost==0)&(~fixed);anchor[change]=reference[change]
    shift=B@anchor;R=B[:,free].tocsr()
    T=sparse.eye(len(free),format='csr');transform=dict(applied=False)
    if coordinate_face is not None:
        F=sparse.csr_matrix(coordinate_face)[:,free].copy()
        assert F.shape[1]==len(free)
        # Transform only unpenalized coordinates. Native variable bounds are
        # explicitly retained below, so rotation never replaces the trust box.
        F=F.multiply((cost[free]==0)[None,:]).tocsr();F.eliminate_zeros()
        cols=np.flatnonzero(np.asarray(abs(F).sum(axis=0)).ravel()>0)
        if 0<len(cols)<=256:
            M=F[:,cols].toarray();norm=np.max(abs(M),axis=1);M=M[norm>0]/norm[norm>0,None]
            _,singular,Vt=linalg.svd(M,full_matrices=True)
            rank=int(np.sum(singular>max(singular,default=1)*1e-10));V=Vt.T
            scale=np.ones(len(cols));scale[:rank]=np.exp2(-12)/singular[:rank]
            local=V*scale[None,:];inverse=(V.T/scale[:,None]);identity_error=float(np.max(abs(local@inverse-np.eye(len(cols)))))
            assert identity_error<1e-8
            T=T.tolil();T[np.ix_(cols,cols)]=local;T=T.tocsr();T.eliminate_zeros()
            transform=dict(applied=True,columns=free[cols].tolist(),rank=rank,normal_unit=float(np.exp2(-12)),identity_error=identity_error,condition=float(scale.max()/scale.min()))
    transformed_cost=np.asarray(T.T@cost[free]).ravel()
    assert np.array_equal(transformed_cost,cost[free]),'zero_cost_subspace_only'

    reduction=dict(reduction,monotone_endpoint_eliminations=proof,remaining_variables=len(free),coordinate_transform=transform)
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
    center=np.clip(anchor,low[-n:],high[-n:]);values=B@center;all_ids=np.arange(B.shape[0])
    selected=set(map(int,maxima(eligible,original_violation(values)[eligible])))
    reduction=dict(reduction,support_groups=len(lookup),initial_rows=len(selected),selection='support-diverse subset generation in original units; original full-row gates unchanged',seed_eligible_rows=len(eligible),seed_omitted_rows=B.shape[0]-len(eligible))
    if callback:callback(reduction)
    history=[];last_x=last_y=None;zero=sparse.csr_matrix((n,n));nf=len(free)
    eye=sparse.eye(nf,format='csr');lb=low[-n:][free];ub=high[-n:][free]
    lower=np.flatnonzero(np.isfinite(lb));upper=np.flatnonzero(np.isfinite(ub))
    for iteration in range(18):
        remaining=deadline-time.monotonic()-2
        if remaining<=.5:break
        ids=np.asarray(sorted(selected));up=np.flatnonzero(np.isfinite(hi[ids]));down=np.flatnonzero(np.isfinite(lo[ids]))
        C0=sparse.vstack([R[ids[up]],-R[ids[down]],eye[upper],-eye[lower]],format='csr')
        rhs=np.r_[hi[ids[up]]-shift[ids[up]],-lo[ids[down]]+shift[ids[down]],ub[upper]-anchor[free][upper],-lb[lower]+anchor[free][lower]]
        C=(C0@T).tocsr();rownorm=np.asarray(abs(C).max(axis=1).toarray()).ravel()
        exponents=np.clip(-np.floor(np.log2(np.maximum(rownorm,1e-30))).astype(int),-20,20);rs=np.exp2(exponents)
        C=C.multiply(rs[:,None]).tocsr();scaled_rhs=rhs*rs
        t=time.monotonic();ans=linprog(transformed_cost,C,scaled_rhs,[(-np.inf,np.inf)]*nf,options=dict(time_limit=min(12.,remaining)))
        record=dict(iteration=iteration,selected_rows=len(ids),seconds=time.monotonic()-t,status=ans.message,status_code=int(ans.status),iterations=int(ans.nit),backend_diagnostics=getattr(ans,'diagnostics',{}),transformed_nnz=int(C.nnz))
        x=anchor.copy();x[free]+=T@ans.x;side_dual=-ans.ineqlin.marginals*rs;dy=np.zeros(B.shape[0])
        np.add.at(dy,ids[up],side_dual[:len(up)]);np.add.at(dy,ids[down],-side_dual[len(up):len(up)+len(down)])
        owner=np.where((dy>=0)[:,None],mapping['upper_owner'],mapping['lower_owner']);y=np.zeros(A.shape[0]);np.add.at(y,owner[:,0].astype(int),dy*owner[:,1])
        offset=len(up)+len(down);y[-n+free[upper]]+=side_dual[offset:offset+len(upper)];y[-n+free[lower]]-=side_dual[offset+len(upper):]
        y[-n+np.flatnonzero(fixed)]=-(cost+A.T@y)[fixed]
        metrics=qp_residuals(zero,cost,A,low,high,x,y);record['full_original_metrics']=metrics
        if not residual_gate(metrics):
            proposal=y.copy();proposal[-n:]-=cost+A.T@y;polished=qp_residuals(zero,cost,A,low,high,x,proposal);record['polish_metrics']=polished
            if residual_gate(polished):y,metrics=proposal,polished
        last_x,last_y=x,y
        if ans.success and residual_gate(metrics):
            history.append(record);print('exchange_iteration',record,flush=True)
            return x,y,dict(passed=True,status='Invertible active-face coordinates with original LP certificate',status_code=0,seconds=time.monotonic()-started,
                reduction=reduction,history=history,residuals=metrics,objective=float(cost@x),all_original_rows_verified=True,
                numerical_backend='active_face_coordinates_original_lp_certificate_r15')
        violation=original_violation(B@x);violated=np.flatnonzero(violation>1e-9)
        fresh=set(map(int,maxima(violated,violation[violated])))-selected if len(violated) else set()
        absent=np.asarray([i for i in violated if int(i) not in selected],dtype=int)
        if len(absent):
            k=min(4096,len(absent));fresh.update(map(int,absent[np.argpartition(violation[absent],-k)[-k:]]))
        record.update(violated_reduced_rows=len(violated),added_rows=len(fresh));history.append(record);print('exchange_iteration',record,flush=True)
        if not fresh:break
        selected.update(fresh)
    return last_x,last_y,dict(selected_rows=sorted(selected),passed=False,status='Active-face coordinates without original certificate',status_code=4,
        seconds=time.monotonic()-started,reduction=reduction,history=history,numerical_backend='active_face_coordinates_original_lp_certificate_r15')
