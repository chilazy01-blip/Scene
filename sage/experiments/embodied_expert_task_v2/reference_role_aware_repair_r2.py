"""Bounded kinematic feasibility repair; never performs integration or inference."""
import time
from types import SimpleNamespace
from sage.experiments.embodied_expert_task_v2.reference_role_aware_validation_r2 import validate_pose
import numpy as np
import mujoco
from scipy.optimize import minimize,least_squares
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles,contacts

def repair(model,state,plan,limits,deadline,initial=None):
    data=mujoco.MjData(model);nq=model.nq
    data.time=state[0];data.qpos[:]=state[1:1+nq];data.qvel[:]=state[1+nq:]
    mujoco.mj_forward(model,data);q0=data.qpos.copy()
    names,roles=names_and_roles(model,{mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) for i in range(model.ngeom) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) or '').startswith('box_')})
    jids=[i for i in range(model.njnt) if model.jnt_type[i]==mujoco.mjtJoint.mjJNT_HINGE]
    qids=[0,1]+[int(model.jnt_qposadr[j]) for j in jids]
    vids=[0,1]+[int(model.jnt_dofadr[j]) for j in jids]
    bounds=[(-.03,.03)]*2; scales=[.03,.03];joint_names=[]
    for j in jids:
        name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j);joint_names.append(name)
        amount=.35 if 'hand' in name else .1 if any(k in name for k in ('hip','knee','ankle')) else .25
        q=q0[model.jnt_qposadr[j]];lo,hi=-amount,amount
        if model.jnt_limited[j]:lo=max(lo,float(model.jnt_range[j,0]-q));hi=min(hi,float(model.jnt_range[j,1]-q))
        bounds.append((lo,hi));scales.append(amount)
    if 'previous_qpos' in plan:
        previous=np.asarray(plan['previous_qpos']);dt=float(plan['dt'])
        speeds=[1.,1.]+[50. if 'hand' in name else 6. if any(k in name for k in ('shoulder','elbow','wrist')) else 50. for name in joint_names]
        bounds=[(max(lo,previous[qid]-speed*dt-q0[qid]),min(hi,previous[qid]+speed*dt-q0[qid])) for (lo,hi),qid,speed in zip(bounds,qids,speeds)]
        if any(lo>=hi for lo,hi in bounds):raise ValueError('temporal_and_pose_bounds_infeasible')
    feet=[i for i in range(model.nbody) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,i) or '').endswith('ankle_roll_link')]
    palms=[int(model.geom_bodyid[mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'gripper0_'+side+'_g0_col')]) for side in ('left','right')]
    assert len(feet)==2 and len(palms)==2,(feet,palms)
    anchors={b:(data.xpos[b].copy(),data.xmat[b].reshape(3,3).copy()) for b in feet+palms}
    pairs={tuple(sorted([int(c.geom1),int(c.geom2)])) for c in data.contact[:data.ncon]}
    pairs.update(tuple(sorted((names.index(a),names.index(b)))) for a,b in plan.get('contact_pairs',[]))
    history=[];x=np.zeros(len(qids)) if initial is None else np.asarray(initial,dtype=float);x=np.clip(x,np.asarray(bounds)[:,0],np.asarray(bounds)[:,1]);cache={};evaluations=0;searching=False
    class FeasibleFound(Exception):pass
    def evaluate(x):
        nonlocal evaluations
        if time.monotonic()>deadline:raise TimeoutError('bounded reference repair deadline')
        if 'x' in cache and np.array_equal(x,cache['x']):return cache
        evaluations+=1;data.qpos[:]=q0;data.qpos[qids]+=x;mujoco.mj_forward(model,data)
        eq=[];ineq=[];eqj=[];ineqj=[]
        def jac(body,point):
            jp=np.zeros((3,model.nv));jr=np.zeros((3,model.nv));mujoco.mj_jac(model,data,jp,jr,point,body);return jp[:,vids],jr[:,vids]
        for body in feet:
            pos,rot=anchors[body];rv=Rotation.from_matrix(data.xmat[body].reshape(3,3)@rot.T).as_rotvec();eq.extend((data.xpos[body]-pos)/.01);eq.extend(rv/.1)
            jp,jr=jac(body,data.xpos[body]);a=np.linalg.norm(rv);xv,yv,zv=rv;sk=np.array([[0,-zv,yv],[zv,0,-xv],[-yv,xv,0]]);coef=1/12 if a<1e-5 else 1/a**2-(1+np.cos(a))/(2*a*np.sin(a));ji=np.eye(3)-.5*sk+coef*sk@sk;eqj.extend(jp/.01);eqj.extend(ji@jr/.1)
        for body in palms:
            pos,rot=anchors[body];dp=np.linalg.norm(data.xpos[body]-pos);dr=np.linalg.norm(Rotation.from_matrix(data.xmat[body].reshape(3,3)@rot.T).as_rotvec())
            ineq.extend([(.035-dp)/.035,(.08-dr)/.08])
            jp,jr=jac(body,data.xpos[body]);rv=Rotation.from_matrix(data.xmat[body].reshape(3,3)@rot.T).as_rotvec();ineqj.extend([-((data.xpos[body]-pos)/max(dp,1e-12))@jp/.035,-rv@jr/max(dr,1e-12)/.08])
        distances={}
        contact_distances={};contact_jac={};distance_jac={}
        for con in data.contact[:data.ncon]:
            pair=tuple(sorted((int(con.geom1),int(con.geom2))))
            if float(con.dist)<contact_distances.get(pair,float('inf')):
                contact_distances[pair]=float(con.dist);jp1,_=jac(int(model.geom_bodyid[con.geom1]),con.pos);jp2,_=jac(int(model.geom_bodyid[con.geom2]),con.pos);contact_jac[pair]=con.frame[:3]@(jp2-jp1)
        for pair in sorted(pairs):
            a,b=pair
            if pair in contact_distances:dist=contact_distances[pair];gradient=contact_jac[pair]
            else:
                points=np.zeros(6);rawdist=float(mujoco.mj_geomDistance(model,data,a,b,.005,points));dist=max(0.,rawdist);direction=points[3:]-points[:3]
                if np.linalg.norm(direction)<1e-12:gradient=np.zeros(len(qids))
                else:
                    normal=direction/(rawdist if abs(rawdist)>1e-12 else np.linalg.norm(direction));jp1,_=jac(int(model.geom_bodyid[a]),points[:3]);jp2,_=jac(int(model.geom_bodyid[b]),points[3:]);gradient=normal@(jp2-jp1)
            distances[pair]=dist;distance_jac[pair]=gradient
            rolepair={roles[a],roles[b]};allowed=rolepair in ({'foot','floor'},{'hand','object'}) or not bool(rolepair & {'robot','hand','foot'})
            ineq.append((dist+((.0049 if rolepair=={'hand','object'} else limits['max_penetration_m']) if allowed else -.0003))/.01);ineqj.append(gradient/.01)
        # Preserve geometric access to each grasp; actual force closure remains unverified.
        for side in plan.get('grasp_sides',('left','right')):
            ds=[(v,(a,b)) for (a,b),v in distances.items() if 'object' in (roles[a],roles[b]) and any(names[g].startswith('gripper0_'+side+'_') for g in (a,b))]
            if ds:
                value,pair=min(ds);ineq.append((.003-value)/.01);ineqj.append(-distance_jac[pair]/.01)
        cache.clear();cache.update(x=x.copy(),eq=np.asarray(eq),ineq=np.asarray(ineq),eq_jac=np.asarray(eqj),ineq_jac=np.asarray(ineqj),qpos=data.qpos.copy())
        if searching and np.max(np.abs(cache['eq']))<=1e-4 and np.min(cache['ineq'])>=-1e-6 and all(lo-1e-10<=v<=hi+1e-10 for v,(lo,hi) in zip(x,bounds)):
            checked=validate_pose(model,state,data.qpos.copy(),plan.get('contact_pairs',[]),limits,grasp_sides=plan.get('grasp_sides',('left','right')))
            if checked['passed']:raise FeasibleFound(x.copy())
        return cache
    def objective(x):return float(np.sum((x/np.asarray(scales))**2))
    for outer in range(plan['max_constraint_growth_rounds']):
        cache.clear()
        searching=True
        try:
            if plan.get('solver')=='trf':
                opt=least_squares(lambda z:np.r_[10*evaluate(z)['eq'],np.minimum(evaluate(z)['ineq']-.0001,0),.0000001*z/np.asarray(scales)],x,jac=lambda z:np.vstack([10*evaluate(z)['eq_jac'],(evaluate(z)['ineq']<.0001)[:,None]*evaluate(z)['ineq_jac'],np.diag(.0000001/np.asarray(scales))]),bounds=np.asarray(bounds).T,max_nfev=plan['max_iterations_per_witness'],ftol=1e-12,xtol=1e-12,gtol=1e-12)
                iterations=opt.nfev;score=objective(opt.x)
            else:
                opt=minimize(objective,x,jac=lambda z:2*z/np.asarray(scales)**2,method='SLSQP',bounds=bounds,constraints=[dict(type='eq',fun=lambda z:evaluate(z)['eq'],jac=lambda z:evaluate(z)['eq_jac']),dict(type='ineq',fun=lambda z:evaluate(z)['ineq'],jac=lambda z:evaluate(z)['ineq_jac'])],options=dict(maxiter=plan['max_iterations_per_witness'],ftol=1e-9,disp=False))
                iterations=opt.nit;score=opt.fun
        except FeasibleFound as found:
            opt=SimpleNamespace(x=found.args[0],success=True,message='independently validated feasible pose found');iterations=0;score=objective(opt.x)
        finally:searching=False
        x=opt.x;e=evaluate(x);c=contacts(model,data,names,roles,limits)
        history.append(dict(round=outer,optimizer_success=bool(opt.success),message=str(opt.message),iterations=int(iterations),objective=float(score),max_equality_residual=float(np.max(np.abs(e['eq']))),min_inequality=float(np.min(e['ineq'])),original_contact_violations=c['violations'],active_pairs=len(pairs)))
        new={tuple(sorted([int(v.geom1),int(v.geom2)])) for v in data.contact[:data.ncon]}-pairs
        if not new:break
        pairs.update(new)
    e=evaluate(x);c=contacts(model,data,names,roles,limits)
    passed=bool(np.max(np.abs(e['eq']))<=1e-4 and np.min(e['ineq'])>=-1e-6 and not c['violations'])
    return dict(passed=passed,history=history,evaluations=evaluations,delta=x.tolist(),joint_names=joint_names,qpos=e['qpos'].tolist(),contact_diagnostics=c,foot_position_bound_m=1e-5,foot_orientation_bound_rad=1e-4,physics_steps=0,policy_forwards=0)
