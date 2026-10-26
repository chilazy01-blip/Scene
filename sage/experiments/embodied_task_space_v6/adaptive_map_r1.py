"""Exact knot insertion preserves a whole incumbent before adding local freedom.

The reference time grid, phase endpoints, source progression and original hard
rate/range/stopping constraints are unchanged. This module does not search for
or qualify a new robot path.
"""
import numpy as np
from scipy import sparse
from scipy.interpolate import BSpline
from sage.experiments.embodied_task_space_v2.joint_map import JointMap
from sage.experiments.embodied_task_space_v2.reference_chain import assemble
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve


def insertion(phase, additions):
    nk=int(phase['nk']);segments=nk-3
    knots=np.r_[np.zeros(4),np.arange(1,segments)/segments,np.ones(4)]
    mapping=BSpline(knots,np.eye(nk),3)
    for knot in sorted(additions):
        if not np.isfinite(knot) or not 0<knot<1:raise ValueError('interior_knots_only')
        if np.min(abs(mapping.t-float(knot)))<1e-10:raise ValueError('new_simple_knots_only')
        mapping=mapping.insert_knot(float(knot))
    basis=BSpline.design_matrix(phase['progress'],mapping.t,3).toarray()
    transform=mapping.c
    if np.max(abs(basis@transform-phase['basis']))>1e-12:raise ValueError('basis_insertion_not_exact')
    updated=dict(phase,basis=basis,nk=basis.shape[1],greville=np.array([mapping.t[k+1:k+4].mean() for k in range(basis.shape[1])]),knots=mapping.t)
    return updated,transform


def local_plan(ordinary,metadata,contact_field):
    raw=np.asarray(contact_field)
    if raw.shape!=(2,ordinary.n,5) or not np.isfinite(raw).all():raise ValueError('invalid_saved_contact_field')
    failed={i for i,p in enumerate(metadata['phases']) if not p['passed']}
    active=sorted({j for i in failed for j in [i-1,i,i+1] if 0<=j<len(ordinary.phases)})
    result=[]
    for i,phase in enumerate(ordinary.phases):
        knots=[]
        if i in active:
            segments=phase['nk']-3;old=np.arange(1,segments)/segments
            # Midpoints add local curve freedom without altering the old curve.
            candidates=[(j+.5)/segments for j in range(segments)]
            start,end=ordinary.offsets[i:i+2];severity=np.max(raw[:,start:end,:],axis=(0,2))
            if severity.max(initial=0)>0:
                peak=int(np.argmax(severity));u=float(phase['progress'][peak])
                candidates.extend([max(.01,u-.025),min(.99,u+.025)])
            for value in sorted(candidates):
                if value<=0 or value>=1 or np.min(abs(old-value),initial=1)<1e-10:continue
                if knots and abs(value-knots[-1])<1e-10:continue
                knots.append(float(value))
        result.append(knots)
    return dict(failed_phases=sorted(failed),active_phases=active,inserted_knots=result,phase_count=len(result),selection='fixed midpoint refinement on failed stages and immediate neighbors, plus two knots bracketing saved worst contact')


class AdaptiveMap(JointMap):
    def __init__(self,ordinary,plan):
        self.j=ordinary.j;self.sources=ordinary.sources;self.lower=ordinary.lower.copy();self.upper=ordinary.upper.copy()
        self.initial=ordinary.initial.copy();self.incoming=ordinary.incoming.copy();self.phases=[];self.transforms=[];self.plan=plan
        if len(plan['inserted_knots'])!=len(ordinary.phases):raise ValueError('phase_count_changed')
        for phase,knots in zip(ordinary.phases,plan['inserted_knots']):
            refined,transform=insertion(phase,knots);self.phases.append(refined);self.transforms.append(transform)
        self.chain=assemble([p['basis'] for p in self.phases],self.initial,self.incoming)
        self.offsets=np.array(self.chain['control_offsets']);self.n=int(self.offsets[-1]);self.qvars=self.chain['variables'];self.pvars=sum(p['nk']-2 for p in self.phases);self.size=self.qvars+self.pvars
        self.Q=sparse.hstack([self.chain['Q'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.q0=self.chain['q0']
        self.V=sparse.hstack([self.chain['V'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.v0=self.chain['v0']
        self.A=sparse.hstack([self.chain['A'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.a0=self.chain['a0']
        pb=sparse.block_diag([p['basis'][:,1:-1] for p in self.phases],format='csr');self.P=sparse.hstack([sparse.csr_matrix((self.n,self.qvars)),pb],format='csr');self.p0=np.concatenate([p['basis'][:,-1] for p in self.phases])
        ds=[sparse.eye(len(p['basis']))-sparse.diags(np.ones(len(p['basis'])-1),-1) for p in self.phases];D=sparse.block_diag(ds,format='csr');DP=D@self.P;dp0=D@self.p0
        K,off=reserve();self.hard=sparse.vstack([self.Q,self.V,self.A,self.Q+K*.02*self.V,self.P,DP],format='csr')
        self.low=np.r_[np.tile(self.lower,self.n)-self.q0,np.full(self.n*self.j,-.35)-self.v0,np.full(self.n*self.j,-.5)-self.a0,np.tile(self.lower,self.n)-off-self.q0-K*.02*self.v0,-self.p0,-dp0]
        self.high=np.r_[np.tile(self.upper,self.n)-self.q0,np.full(self.n*self.j,.35)-self.v0,np.full(self.n*self.j,.5)-self.a0,np.tile(self.upper,self.n)+off-self.q0-K*.02*self.v0,1-self.p0,np.concatenate([np.full(len(p['basis']),1/s.rows) for p,s in zip(self.phases,self.sources)])-dp0]
        self.hard.eliminate_zeros();mask=np.diff(self.hard.indptr)>0
        assert np.max(self.low[~mask],initial=0)<=2e-8 and np.min(self.high[~mask],initial=0)>=-2e-8
        self.hard=self.hard[mask];self.low=self.low[mask];self.high=self.high[mask]
        self.constant=np.r_[np.tile(self.initial,self.qvars//self.j),np.concatenate([p['greville'][1:-1] for p in self.phases])]
        # Variables shared with an untouched phase are fixed at their incumbent
        # value. Active phases retain their interior and remaining boundary DOFs.
        frozen=set()
        for i,indices in enumerate(self.chain['phase_maps']):
            if i not in plan['active_phases']:frozen.update(int(k) for k in indices.ravel() if k>=0)
        offset=self.qvars
        for i,p in enumerate(self.phases):
            if i not in plan['active_phases']:frozen.update(range(offset,offset+p['nk']-2))
            offset+=p['nk']-2
        self.frozen_variables=np.array(sorted(frozen),dtype=int)
        self.original_map=ordinary

    def prolong(self,x):
        old=self.original_map;x=np.asarray(x)
        if x.shape!=(old.size,) or not np.isfinite(x).all():raise ValueError('invalid_original_variable_vector')
        coefficients=np.asarray(old.chain['coefficient_map']@x[:old.qvars]+old.chain['coefficient_offset']);qoffset=0;poffset=old.qvars
        pieces=[];progress=[]
        for before,after,transform in zip(old.phases,self.phases,self.transforms):
            oldq=coefficients[qoffset:qoffset+before['nk']*self.j].reshape(before['nk'],self.j);qoffset+=before['nk']*self.j
            newq=transform@oldq;pieces.append(newq[3:-3].ravel())
            oldp=np.r_[0.,x[poffset:poffset+before['nk']-2],1.];poffset+=before['nk']-2;progress.append((transform@oldp)[1:-1])
        value=np.concatenate([x[:len(self.phases)*self.j],*pieces,*progress])
        if value.shape!=(self.size,):raise ValueError('prolongation_size_mismatch')
        return value
