"""All-phase affine reference and source-progress maps, with global derivatives."""
import numpy as np
from scipy import sparse
from .reference_chain import assemble
from sage.experiments.embodied_task_space_v1.basis import matrices
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve

class JointMap:
    def __init__(self,sources,durations,initial,incoming,lower,upper):
        self.j=len(initial);self.sources=sources;self.lower=lower;self.upper=upper
        self.phases=[matrices(round(t/.02)+300,s.rows,self.j,initial,incoming) for s,t in zip(sources,durations)]
        self.chain=assemble([v['basis'] for v in self.phases],initial,incoming)
        self.offsets=np.array(self.chain['control_offsets']);self.n=int(self.offsets[-1]);self.qvars=self.chain['variables']
        self.pvars=sum(v['nk']-2 for v in self.phases);self.size=self.qvars+self.pvars
        self.Q=sparse.hstack([self.chain['Q'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.q0=self.chain['q0']
        self.V=sparse.hstack([self.chain['V'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.v0=self.chain['v0']
        self.A=sparse.hstack([self.chain['A'],sparse.csr_matrix((self.n*self.j,self.pvars))],format='csr');self.a0=self.chain['a0']
        pb=sparse.block_diag([v['basis'][:,1:-1] for v in self.phases],format='csr');self.P=sparse.hstack([sparse.csr_matrix((self.n,self.qvars)),pb],format='csr')
        self.p0=np.concatenate([v['basis'][:,-1] for v in self.phases])
        ds=[sparse.eye(len(v['basis']))-sparse.diags(np.ones(len(v['basis'])-1),-1) for v in self.phases]
        D=sparse.block_diag(ds,format='csr');DP=D@self.P;dp0=D@self.p0
        K,off=reserve();self.hard=sparse.vstack([self.Q,self.V,self.A,self.Q+K*.02*self.V,self.P,DP],format='csr')
        self.low=np.r_[np.tile(lower,self.n)-self.q0,np.full(self.n*self.j,-.35)-self.v0,np.full(self.n*self.j,-.5)-self.a0,np.tile(lower,self.n)-off-self.q0-K*.02*self.v0,-self.p0,-dp0]
        self.high=np.r_[np.tile(upper,self.n)-self.q0,np.full(self.n*self.j,.35)-self.v0,np.full(self.n*self.j,.5)-self.a0,np.tile(upper,self.n)+off-self.q0-K*.02*self.v0,1-self.p0,np.concatenate([np.full(len(v['basis']),1/s.rows) for v,s in zip(self.phases,sources)])-dp0]
        self.hard.eliminate_zeros();mask=np.diff(self.hard.indptr)>0
        assert np.max(self.low[~mask],initial=0.)<=2e-8 and np.min(self.high[~mask],initial=0.)>=-2e-8
        self.hard=self.hard[mask];self.low=self.low[mask];self.high=self.high[mask]
        self.constant=np.r_[np.tile(initial,self.qvars//self.j),np.concatenate([v['greville'][1:-1] for v in self.phases])]
        self.initial=initial.copy();self.incoming=incoming.copy()
    def values(self,x):
        return ((self.Q@x+self.q0).reshape(self.n,self.j),self.P@x+self.p0,(self.V@x+self.v0).reshape(self.n,self.j),(self.A@x+self.a0).reshape(self.n,self.j))
    def residual(self,x):
        v=self.hard@x;return max(0.,float(np.max(self.low-v)),float(np.max(v-self.high)))
    def reference_rows(self,tick,velocity=None,stop_step=0):
        Q=self.Q[tick*self.j:(tick+1)*self.j]
        if stop_step:
            count=np.sum(abs(velocity)[None,:]>np.arange(1,stop_step+1)[:,None]*.01,axis=0)
            previous=self.Q[(tick-1)*self.j:tick*self.j] if tick else sparse.csr_matrix(Q.shape)
            Q=Q+sparse.diags(count)@(Q-previous)
        return Q
    def embed(self,jac,tick,velocity=None,stop_step=0):
        return sparse.csr_matrix(jac[:,:self.j])@self.reference_rows(tick,velocity,stop_step)+sparse.csr_matrix(jac[:,-1,None])@self.P[tick]
    def source_anchor(self,qadr,residual):
        coeff=[]
        for v,s in zip(self.phases,self.sources):
            a=np.array([s.at(p)[0][qadr]-residual for p in v['greville']]);a=np.clip(a,self.lower,self.upper);coeff.append(a.ravel())
        E=self.chain['coefficient_map'];count=np.asarray(E.power(2).sum(axis=0)).ravel()
        desired=np.asarray(E.T@(np.concatenate(coeff)-self.chain['coefficient_offset'])).ravel()/count
        target=np.r_[desired,self.constant[self.qvars:]];direction=target-self.constant
        value=self.hard@self.constant;change=self.hard@direction
        ratios=np.r_[(self.high[change>1e-14]-value[change>1e-14])/change[change>1e-14],(self.low[change<-1e-14]-value[change<-1e-14])/change[change<-1e-14]]
        alpha=max(0.,min(1.,float(ratios.min(initial=1.))))
        x=self.constant+alpha*.999999*direction
        if self.residual(x)>1e-8:x=self.constant.copy();alpha=0.
        return x,dict(source_ray_fraction=alpha,hard_residual=self.residual(x))
