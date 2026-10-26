"""Sparse phase curves with task-space endpoint freedom and exact discrete rates."""
import numpy as np
from scipy import sparse
from scipy.interpolate import BSpline
from sage.experiments.embodied_geometry_feasibility_v1.waypoint_path import phase_progress

def matrices(n, source_rows, joints, initial, initial_velocity, dt=.02):
    progress,ramp=phase_progress(source_rows,n)
    segments=max(4,int(np.ceil((n-25)/100)))
    knots=np.r_[np.zeros(4),np.arange(1,segments)/segments,np.ones(4)]
    basis=BSpline.design_matrix(progress,knots,3).tocsr();nk=basis.shape[1];width=joints+1
    grid=sparse.kron(basis,sparse.eye(width),format='csr')
    qi=(np.arange(n)[:,None]*width+np.arange(joints)).ravel();pi=np.arange(n)*width+joints
    Q=grid[qi];P=grid[pi]
    L=sparse.eye(n,format='csr')-sparse.diags(np.ones(n-1),-1,shape=(n,n),format='csr')
    LJ=sparse.kron(L,sparse.eye(joints),format='csr')
    V=LJ@Q/dt;vb=np.zeros(n*joints);vb[:joints]=-initial/dt
    A=LJ@V/dt;ab=LJ@vb/dt;ab[:joints]-=initial_velocity/dt
    greville=np.array([knots[k+1:k+4].mean() for k in range(nk)])
    return dict(basis=basis.toarray(),Q=Q,P=P,V=V,A=A,DP=L@P,vb=vb,ab=ab,
                greville=greville,nk=nk,progress=progress,ramp=ramp,width=width)

def stopping_weights(basis,tick,velocity,step,dt=.02,acceleration=.5):
    current=basis[tick];previous=np.zeros_like(current) if tick==0 else basis[tick-1]
    count=np.sum(abs(velocity)[None,:]>np.arange(1,step+1)[:,None]*acceleration*dt,axis=0)
    return current[:,None]+(current-previous)[:,None]*count[None,:]

def embed(jacobian,qweights,pweights):
    j=jacobian.shape[1]-1
    return sparse.csr_matrix(np.hstack([np.c_[jacobian[:,:j]*qweights[k],jacobian[:,-1]*pweights[k]] for k in range(len(pweights))]))
