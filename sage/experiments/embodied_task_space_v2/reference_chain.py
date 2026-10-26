"""One reference vector for all phases, with shared rest boundaries and history.

This is algebraic preparation. It neither optimizes a trajectory nor qualifies one.
"""
import numpy as np
from scipy import sparse


def assemble(bases, initial, initial_velocity, dt=.02):
    initial=np.asarray(initial);initial_velocity=np.asarray(initial_velocity)
    if initial.ndim!=1 or initial_velocity.shape!=initial.shape or dt<=0:
        raise ValueError('invalid initial reference history')
    joints=len(initial);count=len(bases)
    if not count:raise ValueError('at least one phase required')
    next_var=count*joints;boundary=np.arange(count*joints).reshape(count,joints)
    rows=[];cols=[];offset=[];maps=[];coefficient_offset=0;control_offsets=[0]
    for phase,b in enumerate(bases):
        b=np.asarray(b)
        if b.ndim!=2 or b.shape[1]<6 or not np.isfinite(b).all():
            raise ValueError('invalid phase basis')
        nk=b.shape[1];local=np.full((nk,joints),-1,dtype=int);fixed=np.zeros((nk,joints))
        if phase:local[:3]=boundary[phase-1]
        else:fixed[:3]=initial
        local[-3:]=boundary[phase]
        for k in range(3,nk-3):
            local[k]=np.arange(next_var,next_var+joints);next_var+=joints
        for k,j in zip(*np.where(local>=0)):
            rows.append(coefficient_offset+k*joints+j);cols.append(local[k,j])
        offset.extend(fixed.ravel());maps.append(local);coefficient_offset+=nk*joints
        control_offsets.append(control_offsets[-1]+len(b))
    E=sparse.csr_matrix((np.ones(len(rows)),(rows,cols)),shape=(coefficient_offset,next_var))
    B=sparse.block_diag([sparse.kron(b,sparse.eye(joints)) for b in bases],format='csr')
    Q=B@E;q0=np.asarray(B@np.asarray(offset)).ravel();n=control_offsets[-1]
    D=sparse.kron(sparse.eye(n)-sparse.diags(np.ones(n-1),-1),sparse.eye(joints),format='csr')
    V=D@Q/dt;v0=D@q0/dt;v0[:joints]-=initial/dt
    A=D@V/dt;a0=D@v0/dt;a0[:joints]-=initial_velocity/dt
    return dict(Q=Q,q0=q0,V=V,v0=v0,A=A,a0=a0,coefficient_map=E,
                coefficient_offset=np.asarray(offset),phase_maps=maps,
                boundaries=boundary,control_offsets=control_offsets,variables=next_var,
                initial=initial.copy(),initial_velocity=initial_velocity.copy())
