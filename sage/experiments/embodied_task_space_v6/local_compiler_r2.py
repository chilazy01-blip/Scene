"""Prepared local refined-curve convex restoration; original final gates retained."""
import time
import numpy as np
from sage.experiments.embodied_task_space_v5.minimax_compiler_r1 import Compiler as Base
from sage.experiments.embodied_task_space_v5.minimax_acceptance_r1 import accept_step,measures
from .anchored_map_r1 import AnchoredMap
from .certified_local_qp_r1 import solve_qp

class Compiler(Base):
    def __init__(self,c,active,residual,sources,stages,spec,refinement_plan,original_variables,saved_arrays):
        super().__init__(c,active,residual,sources,stages,spec)
        self.original_map=self.map
        self.map=AnchoredMap(self.original_map,refinement_plan,original_variables,saved_arrays)
    def hessian(self,cost):
        return np.r_[np.full(self.map.size,.1),np.zeros(len(cost)-self.map.size)]
    def problem(self,x,linear,trust):
        measured=self.current['raw'].ravel()[linear['labels']]
        margin=np.where(measured<=self.spec['contact_tolerance'],np.minimum(.0005,np.maximum(linear['true_h'],0.)*.5),0.)
        guarded=dict(linear,true_h=linear['true_h']-margin)
        cost,A,low,high=super().problem(x,guarded,trust)
        indices=A.shape[0]-A.shape[1]+self.map.frozen_variables
        low[indices]=0.;high[indices]=0.
        return cost,A,low,high
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
            diagonal=self.hessian(cost)
            primal,dual,info=solve_qp(diagonal,cost,A,low,high,seconds)
            record['solvers'].append(dict(level='local_qp',**info));callback.problem(iteration,'local_qp',A,low,high,cost,primal,dual,info,diagonal)
            step=primal[:self.map.size] if info['passed'] else None
            if step is None:
                record['status']='numerical_subproblem_not_admitted';records.append(record);callback(iteration,record,None);return dict(passed=False,reason='numerical_subproblem_not_admitted',iterations=records),current['arrays']
            for scale in self.spec['step_scales']:
                self.check_time(self.spec['audit_reserve_seconds']);delta=step*scale;proposal=x+delta;hard=self.map.residual(proposal);prediction=self.predict_vector(current,linear,delta);predicted=float(current['vector']@current['vector']-prediction@prediction)
                candidate=self.evaluate(proposal);decision=accept_step(current,candidate,hard,self.spec['contact_tolerance']);record['trials'].append(dict(scale=scale,geometry=candidate['meta'],decision=decision,predicted_reduction=predicted));callback.trial(iteration,scale,candidate['meta'],candidate['arrays'],decision)
                if decision['accepted']:
                    x=proposal;current=candidate;record['accepted']=True;record['scale']=scale;break
            if record['accepted']:trust=min(self.spec['trust_rad'],trust*1.2) if record['scale']==1. else max(self.spec['min_trust_rad'],trust*max(record['scale'],.25))
            else:trust*=.5
            record['incumbent_worst_violation']=measures(current)[0];record['incumbent_merit']=current['meta']['merit'];records.append(record);callback(iteration,record,None)
            if trust<self.spec['min_trust_rad']:break
        return dict(passed=bool(current['meta']['passed']),reason='all_original_gates_passed' if current['meta']['passed'] else 'bounded_local_refinement_search_without_qualified_path',iterations=records),current['arrays']
