"""Single-stage minimax restoration with whole-path protected acceptance."""
import time
import numpy as np
from scipy import sparse
from sage.experiments.embodied_task_space_v4.protected_compiler import Compiler as ProtectedBase
from .minimax_acceptance_r1 import accept_step,measures
from .certified_minimax_lp_r1 import solve_lp

class Compiler(ProtectedBase):
    def problem(self,x,linear,trust):
        contact_caps=np.full(60,np.inf)
        m=self.map;n=m.size;nc=60;nt=30;ni=15;size=n+nc+nt+ni+1;rows=[];lo=[];hi=[]
        def pad(A):return sparse.hstack([A,sparse.csr_matrix((A.shape[0],size-n))],format='csr')
        rows.append(pad(m.hard));v=m.hard@x;lo.append(m.low-v);hi.append(m.high-v)
        G=linear['G'];slack=sparse.coo_matrix((-np.ones(len(linear['h'])),(np.arange(len(linear['h'])),linear['groups'])),shape=(len(linear['h']),nc)).tocsr()
        rows.append(sparse.hstack([G/.005,slack,sparse.csr_matrix((G.shape[0],nt+ni+1))],format='csr'));lo.append(np.full(G.shape[0],-np.inf));hi.append(linear['h']/.005)
        if contact_caps is not None:
            for phase,A,e,B,h in linear['endpoints']:
                for jac,err,scale,tolerance,group in [(A,e,.006,.003,phase*2),(B,h,.012,.010,phase*2+1)]:
                    for sign in [1.,-1.]:
                        z=pad(sign*jac/scale).tolil();z[:,n+nc+group]=-np.ones((len(err),1));rows.append(z.tocsr());lo.append(np.full(len(err),-np.inf));hi.append((tolerance-sign*err)/scale)
            for phase,A,e in linear['tracking']:
                for sign in [1.,-1.]:
                    z=pad(sign*A/.006).tolil();z[:,n+nc+nt+phase]=-np.ones((len(e),1));rows.append(z.tocsr());lo.append(np.full(len(e),-np.inf));hi.append(-sign*e/.006)
            for sign in [1.,-1.]:
                z=pad(sign*sparse.eye(n,format='csr')/trust).tolil();z[:,-1]=-np.ones((n,1));rows.append(z.tocsr());lo.append(np.full(n,-np.inf));hi.append(np.zeros(n))
        # Preserve every already-qualified aligned current/worst-stop component.
        # Failing components participate in the maximum-violation epigraph.
        measured=self.current['raw'].ravel()[linear['labels']];allowed=np.where(measured<=self.spec['contact_tolerance'],0.,np.inf)
        rows.append(pad(G/.005));lo.append(np.full(G.shape[0],-np.inf));hi.append(linear['true_h']/.005+allowed)
        # Protect conditions, not fixed joint values, over every terminal stable tick.
        for phase,tick,jac,error,hand_jac,hand_error in linear['protected']:
            for J,e,limit in [(jac,error,.006),(hand_jac,hand_error,.012)]:
                for sign in [1.,-1.]:
                    rows.append(pad(sign*J/limit));lo.append(np.full(len(e),-np.inf));hi.append(1-sign*e/limit)
            for arm in range(2):
                e=error[3*arm:3*arm+3];length=np.linalg.norm(e)
                if length>1e-12:
                    J=sparse.csr_matrix((e/length)[None,:])@jac[3*arm:3*arm+3]
                    rows.append(pad(J/.006));lo.append(np.array([-np.inf]));hi.append(np.array([1-length/.006]))
        rows.append(sparse.eye(size,format='csr'));lo.append(np.r_[np.full(n,-trust),np.zeros(size-n)]);upper=np.r_[np.full(n,trust),np.full(size-n,np.inf)]
        if contact_caps is not None:upper[n:n+nc]=np.maximum(0.,contact_caps)+1e-8
        hi.append(upper);cost=np.zeros(size)
        if contact_caps is None:cost[n:n+nc]=1.
        else:cost[n+nc:n+nc+nt]=1.;cost[n+nc+nt:n+nc+nt+ni]=.01;cost[-1]=.001
        A=sparse.vstack(rows,format='csr');low=np.concatenate(lo);high=np.concatenate(hi)
        base=sparse.hstack([A[:-size],sparse.csr_matrix((A.shape[0]-size,1))],format='csr')
        links=sparse.coo_matrix((np.r_[np.ones(nc+nt),-np.ones(nc+nt)],
            (np.r_[np.arange(nc+nt),np.arange(nc+nt)],np.r_[np.arange(n,n+nc+nt),np.full(nc+nt,size)])),shape=(nc+nt,size+1)).tocsr()
        matrix=sparse.vstack([base,links,sparse.eye(size+1,format='csr')],format='csr')
        lower=np.r_[low[:-size],np.full(nc+nt,-np.inf),low[-size:],0.]
        upper=np.r_[high[:-size],np.zeros(nc+nt),high[-size:],np.inf]
        objective=np.r_[np.zeros(n),np.full(nc+nt,1e-4),np.full(ni,1e-5),1e-6,1.]
        return objective,matrix,lower,upper
    def solve(self,x,callback,deadline):
        self.deadline=deadline;current=self.evaluate(x);self.current=current;callback('initial',dict(geometry=current['meta'],initialization='frozen_whole_path_or_source_anchor'),current['arrays']);records=[]
        selected=set(range(0,self.map.n,self.spec['search_stride']))
        selected.update(t for b in self.map.offsets[1:] for t in range(int(b)-25,int(b)));trust=self.spec['trust_rad'];stop_selected=set()
        for iteration in range(self.spec['max_iterations']):
            if current['meta']['passed']:return dict(passed=True,iterations=records),current['arrays']
            self.check_time(self.spec['audit_reserve_seconds']);self.current=current
            selected.update(v['tick'] for v in current['bad']);stop_selected.update(current['worst']);selected.update(t for t,s in stop_selected)
            linear=self.linearize_hierarchy(x,selected,stop_selected);record=dict(iteration=iteration,trust=trust,accepted=False,solvers=[],trials=[])
            self.check_time(self.spec['audit_reserve_seconds'])
            cost,A,low,high=self.problem(x,linear,trust)
            seconds=min(self.spec['lp_seconds'],self.deadline-time.monotonic()-self.spec['audit_reserve_seconds'])
            primal,dual,info=solve_lp(cost,A,low,high,seconds)
            record['solvers'].append(dict(level='minimax',**info));callback.problem(iteration,'minimax',A,low,high,cost,primal,dual,info)
            step=primal[:self.map.size] if info['passed'] else None
            if step is None:
                record['status']='numerical_subproblem_not_admitted';records.append(record);callback(iteration,record,None);return dict(passed=False,reason='numerical_subproblem_not_admitted',iterations=records),current['arrays']
            for scale in self.spec['step_scales']:
                self.check_time(self.spec['audit_reserve_seconds']);delta=step*scale;proposal=x+delta;hard=self.map.residual(proposal);prediction=self.predict_vector(current,linear,delta);predicted=float(current['vector']@current['vector']-prediction@prediction)
                candidate=self.evaluate(proposal);decision=accept_step(current,candidate,hard,self.spec['contact_tolerance']);record['trials'].append(dict(scale=scale,geometry=candidate['meta'],decision=decision,predicted_reduction=predicted));callback.trial(iteration,scale,candidate['meta'],candidate['arrays'],decision)
                if decision['accepted']:
                    x=proposal;current=candidate;record['accepted']=True;record['scale']=scale;break
            if record['accepted']:trust=min(self.spec['trust_rad'],trust*1.5)
            else:trust*=.5
            record['incumbent_worst_violation']=measures(current)[0];record['incumbent_merit']=current['meta']['merit'];records.append(record);callback(iteration,record,None)
            if trust<self.spec['min_trust_rad']:break
        return dict(passed=bool(current['meta']['passed']),reason='all_original_gates_passed' if current['meta']['passed'] else 'bounded_minimax_search_without_qualified_path',iterations=records),current['arrays']
