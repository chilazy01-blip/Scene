"""Local B-spline deformations around a bit-preserved whole saved incumbent.

This removes floating reevaluation of the original curve at a zero deformation.
It does not canonicalize or round contact values, joint states or acceptance gates.
"""
import numpy as np
from scipy import sparse
from .adaptive_map_r1 import AdaptiveMap
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve

class AnchoredMap(AdaptiveMap):
    def __init__(self,ordinary,plan,original_variables,saved_arrays):
        super().__init__(ordinary,plan)
        self.absolute_anchor=super().prolong(original_variables)
        self.saved_anchor={k:np.asarray(saved_arrays[k]).copy() for k in ['raw_reference','progress','raw_velocity','raw_acceleration']}
        expected=ordinary.values(original_variables)
        for key,value,tolerance in zip(self.saved_anchor,expected,[1e-10,1e-10,1e-9,1e-7]):
            actual=self.saved_anchor[key]
            if actual.shape!=value.shape or not np.isfinite(actual).all() or np.max(abs(actual-value))>tolerance:raise ValueError('anchor_not_original_whole_curve:'+key)
        self.q0=self.saved_anchor['raw_reference'].ravel().copy();self.p0=self.saved_anchor['progress'].copy();self.v0=self.saved_anchor['raw_velocity'].ravel().copy();self.a0=self.saved_anchor['raw_acceleration'].ravel().copy()
        ds=[sparse.eye(len(p['basis']))-sparse.diags(np.ones(len(p['basis'])-1),-1) for p in self.phases];D=sparse.block_diag(ds,format='csr');DP=D@self.P;dp0=D@self.p0
        K,off=reserve();hard=sparse.vstack([self.Q,self.V,self.A,self.Q+K*.02*self.V,self.P,DP],format='csr')
        low=np.r_[np.tile(self.lower,self.n)-self.q0,np.full(self.n*self.j,-.35)-self.v0,np.full(self.n*self.j,-.5)-self.a0,np.tile(self.lower,self.n)-off-self.q0-K*.02*self.v0,-self.p0,-dp0]
        high=np.r_[np.tile(self.upper,self.n)-self.q0,np.full(self.n*self.j,.35)-self.v0,np.full(self.n*self.j,.5)-self.a0,np.tile(self.upper,self.n)+off-self.q0-K*.02*self.v0,1-self.p0,np.concatenate([np.full(len(p['basis']),1/s.rows) for p,s in zip(self.phases,self.sources)])-dp0]
        hard.eliminate_zeros();mask=np.diff(hard.indptr)>0
        if np.max(low[~mask],initial=0)>2e-8 or np.min(high[~mask],initial=0)<-2e-8:raise ValueError('original_anchor_constant_hard_row_failed')
        self.hard=hard[mask];self.low=low[mask];self.high=high[mask];self.constant=np.zeros(self.size)
    def values(self,x):
        x=np.asarray(x)
        if x.shape!=(self.size,) or not np.isfinite(x).all():raise ValueError('invalid_deformation')
        if not np.any(x):return tuple(self.saved_anchor[k].copy() for k in ['raw_reference','progress','raw_velocity','raw_acceleration'])
        return super().values(x)
    def prolong(self,old_variables):
        # This is an affine chart fixed before search; it is not a generic map
        # for substituting a different historical path into an existing chart.
        if not np.array_equal(super().prolong(old_variables),self.absolute_anchor):raise ValueError('different_whole_incumbent')
        return np.zeros(self.size)
