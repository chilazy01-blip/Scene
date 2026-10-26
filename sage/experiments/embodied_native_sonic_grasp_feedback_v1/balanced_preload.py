"""Group-normal lower bounds for already loaded native contact geometry."""
import numpy as np
from scipy.optimize import linprog
ROLES=('thumb','index','middle')
def solve(rows,weight,com,minimum,margin=1.5,cap=6.):
    columns=[];roles=[]
    for c in rows:
        D=np.array(c['frame']).reshape(3,3);u,v=c['friction'][:2];r=np.array(c['position_m'])-com
        for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
            F=c['object_sign']*D.T@local;columns.append(np.r_[F,np.cross(r,F)]);roles.append(c['role'])
    if not columns:return dict(feasible=False,reason='no loaded native hand contacts')
    W=np.array(columns).T;A=np.array([[float(g==role) for role in roles] for g in ROLES]);lower=np.array([minimum[g] for g in ROLES]);z=linprog(np.ones(len(roles)),A_ub=np.r_[A,-A],b_ub=np.r_[np.full(3,cap),-lower],A_eq=W,b_eq=[0,0,margin*weight,0,0,0],bounds=(0,None),method='highs')
    return dict(feasible=bool(z.success),minimum_group_normals_n=dict(minimum),margin=margin,cap_n=cap,group_normals_n={g:float((A@z.x)[i]) for i,g in enumerate(ROLES)} if z.success else None,equilibrium_error=float(np.max(np.abs(W@z.x-[0,0,margin*weight,0,0,0]))) if z.success else None)
