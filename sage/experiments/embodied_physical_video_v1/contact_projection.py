"""Minimum joint correction satisfying local signed contact constraints."""
import numpy as np,mujoco
from scipy.optimize import minimize
def project(m,d,q,c,ids,depth=.007,iterations=15):
    qmap=np.array(c['qpos_by_pin']);adr=qmap[ids];dofs=adr-1
    joints=np.array([np.flatnonzero(m.jnt_qposadr==v)[0] for v in adr])
    ranges=m.jnt_range[joints];x=q.copy();origin=q[adr].copy()
    jp=np.zeros((3,m.nv));jq=np.zeros_like(jp)
    weights=np.array([1. if c['joint_names'][j].startswith(('left_hand','right_hand')) else 5. for j in ids])
    history=[]
    for k in range(iterations):
        d.qpos[:]=x;mujoco.mj_forward(m,d)
        constraints=[];separations=[];pairs=[]
        for ct in d.contact:
            roles={c['roles'][ct.geom1],c['roles'][ct.geom2]}
            if roles!={'hand','object'}:continue
            if ct.dist>-.002:continue
            mujoco.mj_jac(m,d,jp,None,ct.pos,int(m.geom_bodyid[ct.geom1]))
            mujoco.mj_jac(m,d,jq,None,ct.pos,int(m.geom_bodyid[ct.geom2]))
            derivative=ct.frame[:3]@(jq-jp)[:,dofs]
            constraints.append(derivative);separations.append(-depth-ct.dist)
            pairs.append((c['names'][ct.geom1],c['names'][ct.geom2],float(ct.dist)))
        if not constraints or max(separations)<1e-6:break
        A=np.array(constraints);b=np.array(separations)
        offset=x[adr]-origin
        lower=np.maximum(ranges[:,0]+.005-x[adr],-.12)
        upper=np.minimum(ranges[:,1]-.005-x[adr],.12)
        ans=minimize(lambda z:.5*np.sum(weights*(offset+z)**2),np.zeros(len(ids)),jac=lambda z:weights*(offset+z),bounds=list(zip(lower,upper)),constraints=[dict(type='ineq',fun=lambda z:A@z-b,jac=lambda z:A)],method='SLSQP',options=dict(maxiter=100,ftol=1e-11))
        history.append(dict(iteration=k,success=bool(ans.success),worst=float(max(separations)),delta=float(abs(ans.x).max())))
        x[adr]+=ans.x
        if abs(ans.x).max()<1e-8:break
    d.qpos[:]=x;mujoco.mj_forward(m,d)
    return x,history
