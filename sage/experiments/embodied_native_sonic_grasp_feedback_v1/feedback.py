"""Causal contact-force admittance; persistent targets preserve original PD impedance."""
import numpy as np
from scipy.optimize import linprog
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_native_object_transport_v1.metrics import contact_pair
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group
ROLES=('thumb','index','middle')

def advance(reference,desired_contact_torque,measured_contact_torque,kp,lo,hi,dt=.02,gain=2.):
    reference=np.asarray(reference);error=np.asarray(desired_contact_torque)-measured_contact_torque
    delta=np.clip(dt*gain*error/np.asarray(kp),-.006,.006)
    return np.clip(reference+delta,lo,hi)

def allocate(mj,model,data,minimum_normals,wrench):
    h=hand_ids(model);ix=np.array([i for i,n in enumerate(h['names']) if n in RIGHT_CLOSED]);hd=h['dofs'][ix];pid=model.body('payload').id;com=data.xipos[pid]
    W=[];T=[];roles=[];observed=np.zeros(len(ix));count=0
    for i,c in enumerate(data.contact):
        pair=contact_pair(model,c);names=[x['name'] for x in pair]
        if 'payload_surface' not in names:continue
        side=names.index('payload_surface');role=group(pair[1-side]['body']);f=np.zeros(6);mj.mj_contactForce(model,data,i,f)
        if role not in ROLES or f[0]<=1e-5:continue
        assert c.dim==3 and c.geom[1-side]>=0
        J=np.zeros((3,model.nv));mj.mj_jac(model,data,J,None,c.pos,int(model.geom_bodyid[c.geom[1-side]]));D=np.asarray(c.frame).reshape(3,3);sign=1. if side==1 else -1.;r=c.pos-com;u,v=c.friction[:2]
        observed+=J[:,hd].T@(sign*D.T@f[:3]);count+=1
        for local in [[1,u,0],[1,-u,0],[1,0,v],[1,0,-v]]:
            F=sign*D.T@local;W.append(np.r_[F,np.cross(r,F)]);T.append(J[:,hd].T@F);roles.append(role)
    if not W:return dict(feasible=False,reason='no loaded cup contact')
    W=np.array(W).T;T=np.array(T).T;A=np.array([[float(g==x) for g in roles] for x in ROLES]);required=np.array([minimum_normals[g] for g in ROLES]);n=W.shape[1]
    # Actual dry friction is a separate constraint from cup sliding friction.
    efc=np.where(np.asarray(data.efc_type)==int(mj.mjtConstraint.mjCNSTR_FRICTION_DOF),data.efc_force,0.);friction=np.zeros(model.nv);mj.mj_mulJacTVec(model,data,friction,efc)
    mass=np.zeros((model.nv,model.nv));mj.mj_fullM(model,mass,data.qM);inertia=mass@data.qacc
    offset=data.qfrc_bias[hd]-data.qfrc_passive[hd]-friction[hd]+inertia[hd]
    ends=np.array([RIGHT_CLOSED[h['names'][i]]*.5 for i in ix]);lo=np.minimum(0,ends);hi=np.maximum(0,ends);kp=h['kp'][ix];kd=h['kd'];act=h['actuators'][ix]
    tlo=np.maximum(model.actuator_ctrlrange[act,0],kp*(lo-data.qpos[h['qpos'][ix]])-kd*data.qvel[hd]);thi=np.minimum(model.actuator_ctrlrange[act,1],kp*(hi-data.qpos[h['qpos'][ix]])-kd*data.qvel[hd])
    z=linprog(np.ones(n),A_ub=np.r_[A,-A,T,-T],b_ub=np.r_[np.full(3,6.),-required,thi-offset,-tlo+offset],A_eq=W,b_eq=np.array(wrench),bounds=(0,None),method='highs')
    if not z.success:return dict(feasible=False,reason='no friction-and-current-dynamics-compatible contact allocation',measured_contact_torque_nm=observed.tolist(),native_joint_friction_nm=friction[hd].tolist())
    desired=T@z.x
    return dict(feasible=True,desired_contact_torque_nm=desired.tolist(),measured_contact_torque_nm=observed.tolist(),predicted_required_motor_torque_nm=(desired+offset).tolist(),native_joint_friction_nm=friction[hd].tolist(),passive_nm=data.qfrc_passive[hd].tolist(),inertia_nm=inertia[hd].tolist(),bias_nm=data.qfrc_bias[hd].tolist(),desired_wrench=np.array(wrench).tolist(),achieved_proposal_wrench=(W@z.x).tolist(),equilibrium_error=float(np.max(np.abs(W@z.x-wrench))),right_finger_indices=ix.tolist(),contact_count=count,group_normals_n={g:float((A@z.x)[j]) for j,g in enumerate(ROLES)})
