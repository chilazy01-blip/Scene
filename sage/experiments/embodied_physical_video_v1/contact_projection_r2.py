"""Jointly solve contact clearance and command rate limits, without post-clipping."""
import numpy as np,mujoco
from scipy.optimize import minimize
def project(m,d,desired,c,ids,previous,depth=.005,iterations=20):
    qmap=np.array(c['qpos_by_pin']);adr=qmap[ids];dofs=adr-1
    joints=np.array([np.flatnonzero(m.jnt_qposadr==v)[0] for v in adr])
    hand=np.array([c['joint_names'][j].startswith(('left_hand','right_hand')) for j in ids])
    rate=np.where(hand,.24,.08)
    bounds_lo=np.maximum(m.jnt_range[joints,0]+.005,previous[ids]-rate)
    bounds_hi=np.minimum(m.jnt_range[joints,1]-.005,previous[ids]+rate)
    target=desired[adr].copy();x=desired.copy()
    delta=target-previous[ids];fraction=min(1.,float(np.min(rate/np.maximum(abs(delta),1e-12))))
    x[adr]=previous[ids]+fraction*delta
    x[adr]=np.clip(x[adr],bounds_lo,bounds_hi)
    weights=np.where(hand,1.,5.);jp=np.zeros((3,m.nv));jq=np.zeros_like(jp);history=[]
    for k in range(iterations):
        d.qpos[:]=x;mujoco.mj_forward(m,d)
        A=[];b=[];worst=0.
        for ct in d.contact:
            roles={c['roles'][ct.geom1],c['roles'][ct.geom2]}
            robot=bool(roles&{'robot','hand','foot'})
            if not robot or roles=={'foot','floor'}:continue
            allowed=roles=={'hand','object'}
            limit=-depth if allowed else .0002
            if ct.dist>max(limit+.004,.0005):continue
            mujoco.mj_jac(m,d,jp,None,ct.pos,int(m.geom_bodyid[ct.geom1]))
            mujoco.mj_jac(m,d,jq,None,ct.pos,int(m.geom_bodyid[ct.geom2]))
            jac=ct.frame[:3]@(jq-jp)[:,dofs]
            if np.linalg.norm(jac)<1e-10:continue
            A.append(jac);b.append(limit-ct.dist);worst=max(worst,limit-float(ct.dist))
        offset=x[adr]-target
        low=bounds_lo-x[adr];high=bounds_hi-x[adr]
        constraints=[]
        if A:
            aa,bb=np.array(A),np.array(b)
            constraints=[dict(type='ineq',fun=lambda z:aa@z-bb,jac=lambda z:aa)]
        ans=minimize(lambda z:.5*np.sum(weights*(offset+z)**2),np.zeros(len(ids)),jac=lambda z:weights*(offset+z),bounds=list(zip(low,high)),constraints=constraints,method='SLSQP',options=dict(maxiter=80,ftol=1e-10))
        step=ans.x
        history.append(dict(iteration=k,success=bool(ans.success),worst=worst,delta=float(abs(step).max())))
        x[adr]+=step
        if abs(step).max()<1e-5 and worst<1e-5:break
    d.qpos[:]=x;mujoco.mj_forward(m,d)
    return x,history
