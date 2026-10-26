"""Joint solver with exact hard-constraint exchange; every full row is validated."""
import time
import numpy as np
from scipy import sparse
import osqp
from .joint_compiler import Compiler as Base
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve
from sage.experiments.embodied_task_space_v1.feasible_projection import restore

def initial_hard_rows(m,stride):
    K,_=reserve();ds=[sparse.eye(len(v['basis']))-sparse.diags(np.ones(len(v['basis'])-1),-1) for v in m.phases]
    full=sparse.vstack([m.Q,m.V,m.A,m.Q+K*.02*m.V,m.P,sparse.block_diag(ds,format='csr')@m.P],format='csr');full.eliminate_zeros();mask=np.diff(full.indptr)>0
    assert mask.sum()==m.hard.shape[0]
    ticks=set(range(0,m.n,stride))
    for a,b in zip(m.offsets[:-1],m.offsets[1:]):ticks.update(range(int(a),min(int(a)+3,int(b))));ticks.update(range(int(b)-25,int(b)))
    tick_mask=np.zeros(m.n,bool);tick_mask[list(ticks)]=True
    want=np.r_[np.tile(np.repeat(tick_mask,m.j),4),tick_mask,tick_mask]
    return set(map(int,np.flatnonzero(want[mask])))

def violated_rows(m,x,tolerance=1e-8):
    v=m.hard@x;error=np.maximum(m.low-v,v-m.high)
    return set(map(int,np.flatnonzero(error>tolerance))),max(0.,float(error.max()))

class Compiler(Base):
    def solve(self,callback,deadline):
        m=self.map;x,initialization=m.source_anchor(self.qadr,self.residual);selected=set(range(0,m.n,self.spec['search_stride']));stop_selected=set();hard_selected=initial_hard_rows(m,self.spec['hard_stride']);records=[];last=None
        for a,b in zip(m.offsets[:-1],m.offsets[1:]):selected.update([int(a),int(b-26),int(b-25),int(b-1)])
        callback('initialization',dict(**initialization,all_hard_rows=m.hard.shape[0],initial_selected_hard_rows=len(hard_selected)),None)
        for iteration in range(self.spec['max_iterations']):
            if time.monotonic()>=deadline:break
            t=time.monotonic();J,e,G,h=self.linearize(x,selected,stop_selected);linear_seconds=time.monotonic()-t
            size=m.size;H=J.T@J/max(1,len(selected))+1e-5*sparse.eye(size,format='csr');f=np.asarray(J.T@e).ravel()/max(1,len(selected));trust=self.spec['initial_trust_rad'] if iteration==0 else self.spec['trust_rad'];exchange=[];accepted=False
            for inner in range(self.spec['max_hard_exchanges']):
                if time.monotonic()>=deadline:break
                ids=np.array(sorted(hard_selected));hard=m.hard[ids];value=hard@x
                lhs=sparse.vstack([sparse.hstack([hard,sparse.csr_matrix((len(ids),1))]),sparse.hstack([G,-np.ones((G.shape[0],1))]),sparse.eye(size+1)],format='csc')
                lo=np.r_[m.low[ids]-value,np.full(len(h),-np.inf),np.full(size,-trust),0.];hi=np.r_[m.high[ids]-value,h,np.full(size,trust),np.inf]
                solver=osqp.OSQP();solver.setup(P=sparse.block_diag((H,sparse.csc_matrix([[1.]])),format='csc'),q=np.r_[f,10.],A=lhs,l=lo,u=hi,verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=30000,polishing=True,time_limit=min(self.spec['qp_seconds'],max(.01,deadline-time.monotonic())))
                slack=max(0.,float(-h.min(initial=0)))+1e-8;solver.warm_start(x=np.r_[np.zeros(size),slack]);ans=solver.solve();info=dict(status=ans.info.status,status_val=int(ans.info.status_val),iterations=int(ans.info.iter),variables=size+1,rows=lhs.shape[0],selected_hard_rows=len(ids),full_hard_rows=m.hard.shape[0],linear_seconds=linear_seconds,solver_seconds=float(ans.info.run_time),optimal=ans.info.status_val==1)
                if ans.x is None or not np.isfinite(ans.x).all():info['reason']='no_finite_primal';exchange.append(info);break
                primal=ans.x.copy();residual=max(0.,float(np.max(lo-lhs@primal)),float(np.max(lhs@primal-hi)))
                if residual>1e-8:
                    fixed,repair=restore(lhs,lo,hi,primal,min(self.spec['primal_restore_seconds'],max(.01,deadline-time.monotonic())));info['restoration']=repair
                    if fixed is not None:primal=fixed;residual=max(0.,float(np.max(lo-lhs@primal)),float(np.max(lhs@primal-hi)))
                new=x+primal[:-1];violations,full_residual=violated_rows(m,new);info.update(complete_qp_residual=residual,full_hard_residual=full_residual,violated_full_rows=len(violations));exchange.append(info)
                if residual>1e-8:
                    if hasattr(callback,'problem'):callback.problem(iteration,inner,lhs,lo,hi,primal,x,H,f,ids)
                    break
                if not violations:accepted=True;break
                hard_selected.update(violations)
                if inner==self.spec['max_hard_exchanges']-1 and hasattr(callback,'problem'):callback.problem(iteration,inner,lhs,lo,hi,primal,x,H,f,ids)
            if not accepted:
                r=dict(status='numerical_unknown_or_hard_exchange_limit',solver=dict(exchanges=exchange));callback(iteration,r,None);records.append(r);break
            meta,arrays,bad,stops=self.audit(new);r=dict(solver=dict(exchanges=exchange),geometry=meta);callback(iteration,r,arrays);records.append(r);last=(meta,arrays)
            if meta['passed']:return dict(passed=True,iterations=records),arrays
            selected.update(v['tick'] for v in bad);worst={}
            for v in stops:
                severity=max(q['penetration_m'] for q in v['violations'])
                if v['tick'] not in worst or severity>worst[v['tick']][0]:worst[v['tick']]=(severity,v['step'])
            stop_selected.update((k,v[1]) for k,v in worst.items());selected.update(worst);x=new
        return dict(passed=False,iterations=records,reason='bounded_joint_search_without_qualified_path' if last else 'numerical_unknown'),None if last is None else last[1]
