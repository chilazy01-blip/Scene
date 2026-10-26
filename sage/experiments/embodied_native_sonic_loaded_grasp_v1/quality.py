"""Contact wrench qualification; no integration or state mutation."""
import numpy as np
from scipy.optimize import linprog
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_native_sonic_grasp_diagnosis_v1.friction import capacity,velocity_at

ROLES=('thumb','index','middle')
def contacts(mj,model,data,geometric=False):
    payload=model.body('payload').id;rows=[];desk=0.;force=np.zeros(3);torque=np.zeros(3);com=data.xipos[payload]
    for i,c in enumerate(data.contact):
        pair=contact_pair(model,c);names=[x['name'] for x in pair]
        if 'payload_surface' not in names:continue
        side=names.index('payload_surface');other=pair[1-side];role='desk' if other['body']=='generated_desk' else group(other['body'])
        f=np.zeros(6);mj.mj_contactForce(model,data,i,f);sign=1. if side==1 else -1.;D=np.asarray(c.frame).reshape(3,3);F=sign*D.T@f[:3]
        if role=='desk':desk+=F[2]
        if role not in ROLES or (c.dist>=0 if geometric else f[0]<=1e-5):continue
        ob=int(model.geom_bodyid[c.geom[1-side]])
        rel=velocity_at(mj,model,data,payload,c.pos)-velocity_at(mj,model,data,ob,c.pos)
        rows.append(dict(role=role,dim=int(c.dim),friction=np.asarray(c.friction).tolist(),normal_n=max(0.,float(f[0])),frame=D.ravel().tolist(),object_sign=sign,position_m=np.asarray(c.pos).tolist(),distance_m=float(c.dist),slip_m_s=float(np.linalg.norm((D@rel)[1:])),normal_vertical=float(sign*D[0,2])))
        force+=F;torque+=np.cross(c.pos-com,F)
    return rows,dict(hand_force_world_n=force.tolist(),hand_torque_nm=torque.tolist(),desk_force_z_n=float(desk),weight_n=float(model.body_mass[payload]*abs(model.opt.gravity[2])),com_m=com.tolist())

def required_preload(rows,weight,com,margin=1.5,cap=6.):
    columns=[];roles=[]
    for c in rows:
        D=np.array(c['frame']).reshape(3,3);u,v=c['friction'][:2];r=np.array(c['position_m'])-com
        for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
            f=c['object_sign']*D.T@local;columns.append(np.r_[f,np.cross(r,f)]);roles.append(c['role'])
    if not columns:return dict(feasible=False,reason='no contacts')
    W=np.array(columns).T;A=np.array([[float(x==g) for x in roles] for g in ROLES]);b=np.array([0,0,margin*weight,0,0,0])
    z=linprog(np.ones(len(roles)),A_ub=A,b_ub=np.full(3,cap),A_eq=W,b_eq=b,bounds=(0,None),method='highs')
    return dict(feasible=bool(z.success),margin=margin,per_group_cap_n=cap,required_group_normal_n={g:float(sum(z.x[j] for j,x in enumerate(roles) if x==g)) for g in ROLES} if z.success else None,total_normal_n=float(z.fun) if z.success else None)

def evaluate(mj,model,data):
    rows,q=contacts(mj,model,data);q['contacts']=rows;q['capacity']=capacity(rows,q['weight_n'],np.array(q['com_m']));q['maximum_slip_m_s']=max([c['slip_m_s'] for c in rows],default=0.)
    q['qualified']=bool(q['capacity'].get('maximum_weight_multiple',0) is not None and q['capacity'].get('maximum_weight_multiple',0)>=1.25 and q['maximum_slip_m_s']<.02)
    return q
