"""Evaluate the same complete spline on a longer condition source grid.

No source samples are dropped. Knots, coefficients and phase endpoints are
unchanged; phase sampling grows in proportion to the actual source-row count. Every
hard position, rate, acceleration, stopping and progress row is rebuilt.
"""
import copy
import numpy as np
from scipy import sparse
from scipy.interpolate import BSpline
from sage.experiments.embodied_task_space_v2.reference_chain import assemble
from sage.experiments.embodied_geometry_feasibility_v1.waypoint_path import phase_progress
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve
from sage.experiments.embodied_task_space_v6.anchored_map_r1 import AnchoredMap


def condition_map(ordinary,plan,original_variables,anchor,sources):
    nominal_rows=[s.rows for s in ordinary.sources]
    extra=[max(0,int(np.ceil(len(p['basis'])*s.rows/r))-len(p['basis'])) for p,s,r in zip(ordinary.phases,sources,nominal_rows)]
    if not any(extra):
        ordinary.sources=sources
        return AnchoredMap(ordinary,plan,original_variables,anchor),extra
    base=copy.copy(ordinary);base.sources=sources;base.phases=[]
    for old,source,delta in zip(ordinary.phases,sources,extra):
        n=len(old['basis'])+delta
        parameter,ramp=phase_progress(source.rows,n)
        segments=old['nk']-3
        knots=np.r_[np.zeros(4),np.arange(1,segments)/segments,np.ones(4)]
        basis=BSpline.design_matrix(parameter,knots,3).toarray()
        base.phases.append(dict(old,basis=basis,progress=parameter,ramp=ramp))
    base.chain=assemble([p['basis'] for p in base.phases],base.initial,base.incoming)
    base.offsets=np.array(base.chain['control_offsets']);base.n=int(base.offsets[-1])
    base.qvars=base.chain['variables'];base.pvars=sum(p['nk']-2 for p in base.phases);base.size=base.qvars+base.pvars
    for key,offset in [('Q','q0'),('V','v0'),('A','a0')]:
        setattr(base,key,sparse.hstack([base.chain[key],sparse.csr_matrix((base.n*base.j,base.pvars))],format='csr'))
        setattr(base,offset,base.chain[offset])
    pb=sparse.block_diag([p['basis'][:,1:-1] for p in base.phases],format='csr')
    base.P=sparse.hstack([sparse.csr_matrix((base.n,base.qvars)),pb],format='csr')
    base.p0=np.concatenate([p['basis'][:,-1] for p in base.phases])
    # AnchoredMap rebuilds all original hard rows from these exact new samples.
    arrays=dict(zip(['raw_reference','progress','raw_velocity','raw_acceleration'],base.values(original_variables)))
    result=AnchoredMap(base,plan,original_variables,arrays)
    return result,extra
