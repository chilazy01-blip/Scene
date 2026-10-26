"""Prepared gate-aligned restoration with full terminal-window task residuals.

Original hard rows, all-trial contact memory, bounded search, and nonlinear
acceptance are retained. New soft targets and added endpoint protection do not
relax any original robot or physical qualification gate.
"""
import numpy as np
from scipy import sparse
from sage.experiments.embodied_task_space_v7.witness_compiler_r4 import Compiler as Base,solve_qp
from .gate_linearization_r1 import linearize_terminal_window

class Compiler(Base):
    def linearize_hierarchy(self,x,selected,stop_selected):
        ticks,stops=self.contact_witnesses.selections(selected,stop_selected)
        result=linearize_terminal_window(self,x,ticks,stops)
        d=result['descriptors'];emitted={(int(r[0]),int(r[1])) for r in d if r[1]>0}
        record=dict(observations=self.contact_witnesses.observations,selected_ticks=len(ticks),requested_stopping_states=len(stops),emitted_stopping_states=len(emitted),requested_stops_without_contact_rows=[list(v) for v in sorted(stops-emitted)],contact_rows=len(d),release_stopping_rows=int(np.sum((d[:,0]>=self.map.offsets[11])&(d[:,0]<self.map.offsets[12])&(d[:,1]>0))),terminal_hold_after_current_stop=True,terminal_task_samples=len(result['endpoints']))
        self.witness_linearizations.append(record)
        return result

    def problem(self,x,linear,trust):
        cost,A,low,old_high=super().problem(x,linear,trust)
        high=old_high.copy();n=self.map.size;size=A.shape[1];first=self.map.hard.shape[0];k=len(linear['h'])
        high[first:first+k]=linear['true_h']/.005
        changed=set(range(first,first+k));offset=first+k;extra=[];extra_high=[];failing_targets=0;protected_norms=0
        def norm_row(J,e,group,limit,soft):
            length=float(np.linalg.norm(e))
            if length<=1e-12:return
            row=sparse.hstack([(sparse.csr_matrix((e/length)[None,:])@J)/.006,sparse.csr_matrix((1,size-n))],format='lil')
            if soft:row[0,n+60+group]=-1.
            extra.append(row.tocsr());extra_high.append((limit-length)/.006)
        for phase,J,e,B,h in linear['endpoints']:
            for jac,err,scale,old_limit,group in [(J,e,.006,.003,phase*2),(B,h,.012,.010,phase*2+1)]:
                if group%2==0:target=np.full(len(err),.006)
                else:target=np.where(abs(err)>.012,.010,.012)
                for sign in [1.,-1.]:
                    ids=np.arange(offset,offset+len(err));high[ids]=(target-sign*err)/scale;changed.update(ids.tolist());offset+=len(err)
            for arm in range(2):
                error=e[3*arm:3*arm+3];length=float(np.linalg.norm(error));target=.0055 if length>.006 else .006
                failing_targets+=int(length>.006);norm_row(J[3*arm:3*arm+3],error,phase*2,target,True)
                if self.current['meta']['phases'][phase]['passed']:
                    reserve=min(.0005,max(.006-length,0.)*.5)
                    norm_row(J[3*arm:3*arm+3],error,phase*2,.006-reserve,False);protected_norms+=1
        unchanged=np.ones(A.shape[0],dtype=bool);unchanged[list(changed)]=False
        assert np.array_equal(high[unchanged],old_high[unchanged])
        added=sparse.vstack(extra,format='csr')
        matrix=sparse.vstack([A[:-size],added,A[-size:]],format='csr')
        lo=np.r_[low[:-size],np.full(len(extra),-np.inf),low[-size:]];hi=np.r_[high[:-size],extra_high,high[-size:]]
        self.objective_record=dict(original_hard_rows_retained=True,original_bounds_unchanged_except_soft_rows=True,changed_soft_rows=len(changed),added_norm_support_rows=len(extra),protected_norm_rows=protected_norms,failing_palm_interior_targets=failing_targets,terminal_samples=len(linear['endpoints']),palm_gate_m=.006,hand_gate_rad=.012,failed_palm_soft_target_m=.0055,endpoint_clearance_fraction=.5,endpoint_clearance_cap_m=.0005)
        return cost,matrix,lo,hi

    def predict_vector(self,baseline,linear,delta):
        raw=baseline['raw'].copy().ravel();labels=linear['labels'];raw[np.unique(labels)]=0.
        violation=np.maximum(linear['G']@delta-linear['true_h'],0.)/.005;np.maximum.at(raw,labels,violation)
        ends=np.zeros_like(baseline['ends'])
        for phase,J,e,B,h in linear['endpoints']:
            palm=float(np.linalg.norm((e+J@delta).reshape(2,3),axis=1).max());hand=float(abs(h+B@delta).max())
            ends[phase]=np.maximum(ends[phase],[max(0.,palm/.006-1),max(0.,hand/.012-1)])
        return np.r_[raw/np.sqrt(self.map.n),ends.ravel()/np.sqrt(30)]
