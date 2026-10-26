"""Bounded kinematic feasibility repair; never performs integration or inference."""
import time
import numpy as np
import mujoco
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles,contacts

def repair(model,state,plan,limits,deadline,initial=None):
    data=mujoco.MjData(model);nq=model.nq
    data.time=state[0];data.qpos[:]=state[1:1+nq];data.qvel[:]=state[1+nq:]
    mujoco.mj_forward(model,data);q0=data.qpos.copy()
    names,roles=names_and_roles(model,{mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) for i in range(model.ngeom) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) or '').startswith('box_')})
    jids=[i for i in range(model.njnt) if model.jnt_type[i]==mujoco.mjtJoint.mjJNT_HINGE]
    qids=[0,1]+[int(model.jnt_qposadr[j]) for j in jids]
    bounds=[(-.03,.03)]*2; scales=[.03,.03];joint_names=[]
    for j in jids:
        name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j);joint_names.append(name)
        amount=.35 if 'hand' in name else .1 if any(k in name for k in ('hip','knee','ankle')) else .25
        q=q0[model.jnt_qposadr[j]];lo,hi=-amount,amount
        if model.jnt_limited[j]:lo=max(lo,float(model.jnt_range[j,0]-q));hi=min(hi,float(model.jnt_range[j,1]-q))
        bounds.append((lo,hi));scales.append(amount)
    feet=[i for i in range(model.nbody) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,i) or '').endswith('ankle_roll_link')]
    palms=[int(model.geom_bodyid[mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'gripper0_'+side+'_g0_col')]) for side in ('left','right')]
    assert len(feet)==2 and len(palms)==2,(feet,palms)
    anchors={b:(data.xpos[b].copy(),data.xmat[b].reshape(3,3).copy()) for b in feet+palms}
    pairs={tuple(sorted([int(c.geom1),int(c.geom2)])) for c in data.contact[:data.ncon]}
    pairs.update(tuple(sorted((names.index(a),names.index(b)))) for a,b in plan.get('contact_pairs',[]))
    history=[];x=np.zeros(len(qids)) if initial is None else np.asarray(initial,dtype=float);cache={};evaluations=0
    def evaluate(x):
        nonlocal evaluations
        if time.monotonic()>deadline:raise TimeoutError('bounded reference repair deadline')
        if 'x' in cache and np.array_equal(x,cache['x']):return cache
        evaluations+=1;data.qpos[:]=q0;data.qpos[qids]+=x;mujoco.mj_forward(model,data)
        eq=[];ineq=[]
        for body in feet:
            pos,rot=anchors[body];eq.extend((data.xpos[body]-pos)/.01);eq.extend(Rotation.from_matrix(data.xmat[body].reshape(3,3)@rot.T).as_rotvec()/.1)
        for body in palms:
            pos,rot=anchors[body];dp=np.linalg.norm(data.xpos[body]-pos);dr=np.linalg.norm(Rotation.from_matrix(data.xmat[body].reshape(3,3)@rot.T).as_rotvec())
            ineq.extend([(.035-dp)/.035,(.08-dr)/.08])
        distances={}
        contact_distances={}
        for con in data.contact[:data.ncon]:
            pair=tuple(sorted((int(con.geom1),int(con.geom2))))
            contact_distances[pair]=min(contact_distances.get(pair,float('inf')),float(con.dist))
        for pair in sorted(pairs):
            a,b=pair;dist=contact_distances[pair] if pair in contact_distances else max(0.,float(mujoco.mj_geomDistance(model,data,a,b,.005,None)));distances[pair]=dist
            rolepair={roles[a],roles[b]};allowed=rolepair in ({'foot','floor'},{'hand','object'}) or not bool(rolepair & {'robot','hand','foot'})
            ineq.append((dist+(.005 if allowed else -.0002))/.01)
        # Preserve geometric access to each grasp; actual force closure remains unverified.
        for side in ('left','right'):
            ds=[v for (a,b),v in distances.items() if 'object' in (roles[a],roles[b]) and any(names[g].startswith('gripper0_'+side+'_') for g in (a,b))]
            if ds:ineq.append((.003-min(ds))/.01)
        cache.clear();cache.update(x=x.copy(),eq=np.asarray(eq),ineq=np.asarray(ineq),qpos=data.qpos.copy())
        return cache
    def objective(x):return float(np.sum((x/np.asarray(scales))**2))
    for outer in range(plan['max_constraint_growth_rounds']):
        cache.clear()
        opt=least_squares(lambda z:np.r_[10*evaluate(z)['eq'],np.minimum(evaluate(z)['ineq']-.0001,0),.0000001*z/np.asarray(scales)],x,bounds=np.asarray(bounds).T,method='trf',max_nfev=plan['max_iterations_per_witness'],ftol=1e-12,xtol=1e-12,gtol=1e-12)
        x=opt.x;e=evaluate(x);c=contacts(model,data,names,roles,limits)
        history.append(dict(round=outer,optimizer_success=bool(opt.success),message=str(opt.message),iterations=int(opt.nfev),objective=float(objective(x)),max_equality_residual=float(np.max(np.abs(e['eq']))),min_inequality=float(np.min(e['ineq'])),original_contact_violations=c['violations'],active_pairs=len(pairs)))
        new={tuple(sorted([int(v.geom1),int(v.geom2)])) for v in data.contact[:data.ncon]}-pairs
        if not new:break
        pairs.update(new)
    e=evaluate(x);c=contacts(model,data,names,roles,limits)
    passed=bool(np.max(np.abs(e['eq']))<=1e-4 and np.min(e['ineq'])>=-1e-6 and not c['violations'])
    return dict(passed=passed,history=history,evaluations=evaluations,delta=x.tolist(),joint_names=joint_names,qpos=e['qpos'].tolist(),contact_diagnostics=c,foot_position_bound_m=1e-5,foot_orientation_bound_rad=1e-4,physics_steps=0,policy_forwards=0)
