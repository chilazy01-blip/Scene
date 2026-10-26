"""Actuation-aware6D contact allocation to bounded original finger PD references."""
import numpy as np
from scipy.optimize import linprog
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
ROLES=('thumb','index','middle')

def solve(mj,model,data,minimum_normals,previous=None,dt=.02):
    h=hand_ids(model);rids=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);dofs=h['dofs'][rids];qids=h['qpos'][rids];act=h['actuators'][rids]
    pid=model.body('payload').id;com=data.xipos[pid];weight=float(model.body_mass[pid]*abs(model.opt.gravity[2]));columns=[];jointcols=[];roles=[];contacts=[]
    for i,c in enumerate(data.contact):
        pair=contact_pair(model,c);names=[x['name'] for x in pair]
        if 'payload_surface' not in names:continue
        side=names.index('payload_surface');role=group(pair[1-side]['body']);f=np.zeros(6);mj.mj_contactForce(model,data,i,f)
        if role not in ROLES or f[0]<=1e-5:continue
        assert c.dim==3 and c.geom[1-side]>=0
        body=int(model.geom_bodyid[c.geom[1-side]]);J=np.zeros((3,model.nv));mj.mj_jac(model,data,J,None,c.pos,body)
        D=np.asarray(c.frame).reshape(3,3);sign=1. if side==1 else -1.;u,v=c.friction[:2];r=c.pos-com
        for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
            F=sign*D.T@local;columns.append(np.r_[F,np.cross(r,F)]);jointcols.append(J[:,dofs].T@F);roles.append(role)
        contacts.append(dict(role=role,position_m=c.pos.tolist(),body_id=body))
    if not columns:return dict(feasible=False,reason='no actual loaded contact')
    W=np.array(columns).T;T=np.array(jointcols).T;A=np.array([[float(g==x) for g in roles] for x in ROLES]);required=np.array([minimum_normals[x] for x in ROLES]);n=len(columns)
    bias=data.qfrc_bias[dofs];qd=data.qvel[dofs];kp=h['kp'][rids];kd=float(h['kd'])
    endpoint=np.array([RIGHT_CLOSED[h['names'][i]]*.5 for i in rids]);lo=np.minimum(0,endpoint);hi=np.maximum(0,endpoint)
    # A desired contact load requires motor torque J_hand.T*F_object + own bias.
    # Constrain both original native effort and the unchanged[0,.5closed] target envelope.
    tlo=np.maximum(model.actuator_ctrlrange[act,0],kp*(lo-data.qpos[qids])-kd*qd)
    thi=np.minimum(model.actuator_ctrlrange[act,1],kp*(hi-data.qpos[qids])-kd*qd)
    rhs=np.r_[np.full(3,6.),-required,thi-bias,-tlo+bias]
    Aub=np.r_[A,-A,T,-T];beq=np.array([0,0,weight,0,0,0.])
    z=linprog(np.ones(n),A_ub=Aub,b_ub=rhs,A_eq=W,b_eq=beq,bounds=(0,None),method='highs')
    if not z.success:return dict(feasible=False,reason='no original-effort/target-bounded wrench solution',solver_message=z.message)
    torque=T@z.x+bias;raw=data.qpos[qids]+(torque+kd*qd)/kp
    target=np.zeros(len(h['names']));target[rids]=raw;raw_target=target.copy()
    clipped=False
    if previous is not None:
        prev=np.asarray(previous);change=np.clip(target-prev,-.006,.006);clipped=bool(np.any(change!=target-prev));target=prev+change
    achieved=W@z.x
    return dict(feasible=True,target_rad=target.tolist(),raw_target_rad=raw_target.tolist(),right_motor_torque_nm=torque.tolist(),right_finger_names=[h['names'][i] for i in rids],group_normals_n={g:float((A@z.x)[j]) for j,g in enumerate(ROLES)},desired_wrench=achieved.tolist(),weight_n=weight,maximum_wrench_error=float(np.max(np.abs(achieved-beq))),target_slew_limited=clipped,contact_count=len(contacts),limitation='quasistatic contact-force proposal under actual finger torque/target bounds; motor references slew-limited, actual world wrench must be measured; not a dynamic success proof')
