"""Zero-step arm/hand target repair with explicit native-contact residuals.

A solver result is a geometric target only. Runtime safety is checked separately
on every actual physical step; this module never integrates or runs a policy.
"""
import numpy as np
import mujoco
from scipy.optimize import least_squares, minimize
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_expert_task_v1.quality import names_and_roles,contacts

class UpperTargetSolver:
    def __init__(self,model,qpos_by_pin,groups,plan):
        self.model=model;self.data=mujoco.MjData(model);self.mapping=qpos_by_pin;self.groups=groups;self.plan=plan
        self.arm=np.asarray(groups['left_arm']+groups['right_arm']);self.hand=np.asarray(groups['left_hand']+groups['right_hand']);self.upper=np.asarray(sorted(set(self.arm)|set(self.hand)));self.qids=qpos_by_pin[self.upper];self.dofs=self.qids-1
        self.names,self.roles=names_and_roles(model,{mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g) for g in range(model.ngeom) if (mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,g) or '').startswith('box_')});self.palms=[int(model.geom_bodyid[self.names.index('gripper0_'+s+'_g0_col')]) for s in ('left','right')]
        self.bounds=np.asarray([model.jnt_range[int(np.flatnonzero(model.jnt_qposadr==q)[0])] for q in self.qids]);self.last=None
    def solve(self,actual_q,posture_by_pin,palm_positions,palm_rotations):
        model=self.model;data=self.data;data.qpos[:]=actual_q;data.qvel[:]=0;desired=np.clip(posture_by_pin[self.upper],self.bounds[:,0],self.bounds[:,1]);amount=np.asarray([self.plan['max_hand_posture_departure_rad'] if k in self.hand else self.plan['max_arm_posture_departure_rad'] for k in self.upper]);lo=np.maximum(self.bounds[:,0],desired-amount);hi=np.minimum(self.bounds[:,1],desired+amount);initial=np.clip(desired if self.last is None else self.last,lo,hi);pairs={tuple(sorted((self.names.index(a),self.names.index(b)))) for a,b in self.plan.get('contact_pairs',[])};cache={};jacp=np.zeros((3,model.nv));jacr=np.zeros((3,model.nv))
        pairs={pair for pair in pairs if bool({self.roles[pair[0]],self.roles[pair[1]]}&{'robot','hand','foot'}) and {self.roles[pair[0]],self.roles[pair[1]]}!={'foot','floor'}}
        def geometry(q):
            data.qpos[:]=actual_q;data.qpos[self.qids]=q;mujoco.mj_forward(model,data)
            native={}
            for c in data.contact[:data.ncon]:
                a,b=int(c.geom1),int(c.geom2);pair=tuple(sorted((a,b)));kinds={self.roles[a],self.roles[b]};robot=bool(kinds & {'robot','hand','foot'})
                if not robot or kinds=={'foot','floor'}:continue
                if pair not in native or c.dist<native[pair][0]:native[pair]=(float(c.dist),np.array(c.pos),np.array(c.frame).reshape(3,3)[0].copy()*(1 if pair==(a,b) else -1))
            return native
        def distance_and_jac(native,pair):
            a,b=pair
            if pair in native:
                distance,point,normal=native[pair];p1=p2=point
            else:
                points=np.zeros(6);raw=float(mujoco.mj_geomDistance(model,data,a,b,.005,points));distance=.005 if raw==0 and not np.any(points) else max(0.,raw);p1,p2=points[:3],points[3:];direction=p2-p1
                normal=direction/(raw if abs(raw)>1e-12 else max(np.linalg.norm(direction),1e-12))
            j1=np.zeros((3,model.nv));j2=np.zeros((3,model.nv));mujoco.mj_jac(model,data,j1,None,p1,int(model.geom_bodyid[a]));mujoco.mj_jac(model,data,j2,None,p2,int(model.geom_bodyid[b]));return distance,normal@(j2-j1)[:,self.dofs]
        native=geometry(desired)
        def acceptable(native):
            bad=[]
            for (a,b),(distance,_,_) in native.items():
                limit=-self.plan['target_hand_penetration_m'] if {self.roles[a],self.roles[b]}=={'hand','object'} else -1e-6
                if distance<limit-1e-6:bad.append(dict(pair=[self.names[a],self.names[b]],distance=distance,minimum=limit))
            position=max(float(np.linalg.norm(data.xpos[b]-palm_positions[k])) for k,b in enumerate(self.palms))
            orientation=max(float(np.linalg.norm(Rotation.from_matrix(data.xmat[b].reshape(3,3)@palm_rotations[k].T).as_rotvec())) for k,b in enumerate(self.palms))
            return not bad and position<=self.plan['palm_position_tolerance_m'] and orientation<=self.plan['palm_rotation_tolerance_rad'],position,orientation,bad
        ok,position,orientation,bad=acceptable(native)
        if ok:
            command=posture_by_pin.copy();command[self.upper]=desired;self.last=desired.copy()
            return command,dict(passed=True,palm_position_error=position,palm_rotation_error=orientation,violations=bad,optimizer_evaluations=0,optimizer_success=True,feasible_reference_reused=True,qpos=data.qpos.copy())
        native=geometry(initial);pairs.update(native)
        for outer in range(3):
            ordered=sorted(pairs);cache.clear()
            def evaluate(q):
                if 'q' in cache and np.array_equal(q,cache['q']):return cache['residual'],cache['jacobian']
                native=geometry(q);res=[];jac=[]
                for k,body in enumerate(self.palms):
                    mujoco.mj_jacBody(model,data,jacp,jacr,body);res.extend((data.xpos[body]-palm_positions[k])/.015);jac.extend(jacp[:,self.dofs]/.015)
                    rot=Rotation.from_matrix(data.xmat[body].reshape(3,3)@palm_rotations[k].T).as_rotvec();res.extend(rot/.15);jac.extend(jacr[:,self.dofs]/.15)
                weights=np.asarray([.3 if k in self.hand else .1 for k in self.upper]);res.extend(weights*(q-desired));jac.extend(np.diag(weights))
                for pair in ordered:
                    a,b=pair;kinds={self.roles[a],self.roles[b]};allowed=kinds=={'hand','object'};minimum=-self.plan['target_hand_penetration_m']+.0001 if allowed else self.plan['forbidden_target_gap_m']+.0001
                    if pair in native:distance,point,normal=native[pair]
                    else:
                        distance=float(mujoco.mj_geomDistance(model,data,a,b,.0005,None));point=np.zeros(3);normal=np.zeros(3)
                        if distance<=0:distance=.0005
                    violation=min(0.,distance-minimum);res.append(violation/.0005)
                    if violation<0 and pair in native:
                        j1=np.zeros((3,model.nv));j2=np.zeros((3,model.nv));mujoco.mj_jac(model,data,j1,None,point,int(model.geom_bodyid[a]));mujoco.mj_jac(model,data,j2,None,point,int(model.geom_bodyid[b]));jac.append(normal@(j2-j1)[:,self.dofs]/.0005)
                    else:jac.append(np.zeros(len(q)))
                cache.clear();cache.update(q=q.copy(),residual=np.asarray(res),jacobian=np.asarray(jac));return cache['residual'],cache['jacobian']
            opt=least_squares(lambda q:evaluate(q)[0],initial,jac=lambda q:evaluate(q)[1],bounds=(lo,hi),max_nfev=self.plan['ik_max_evaluations'],ftol=1e-7,xtol=1e-7,gtol=1e-7);initial=opt.x;native=geometry(initial);new=set(native)-pairs
            if not new:break
            pairs.update(new)
        native=geometry(initial)
        ok,_,_,_=acceptable(native)
        if not ok:
            pairs.update(native)
            ordered=sorted(pairs)
            def constraints(q):
                native=geometry(q);values=[];jac=[]
                for a,b in ordered:
                    allowed={self.roles[a],self.roles[b]}=={'hand','object'}
                    minimum=-self.plan['target_hand_penetration_m']+.0001 if allowed else self.plan['forbidden_target_gap_m']+.0001
                    distance,derivative=distance_and_jac(native,(a,b))
                    values.append((distance-minimum)/.001);jac.append(derivative/.001)
                for k,body in enumerate(self.palms):
                    mujoco.mj_jacBody(model,data,jacp,jacr,body)
                    for error,derivative,tolerance in [(data.xpos[body]-palm_positions[k],jacp[:,self.dofs],self.plan['palm_position_tolerance_m']), (Rotation.from_matrix(data.xmat[body].reshape(3,3)@palm_rotations[k].T).as_rotvec(),jacr[:,self.dofs],self.plan['palm_rotation_tolerance_rad'])]:
                        length=max(float(np.linalg.norm(error)),1e-15);values.append((tolerance-length)/tolerance);jac.append(-(error@derivative)/(length*tolerance))
                return np.asarray(values),np.asarray(jac)
            def objective(q):
                residual,jac=evaluate(q);residual=residual[:12+len(q)];jac=jac[:12+len(q)];return .5*float(residual@residual),residual@jac
            for _ in range(6):
                cache.clear()
                polished=minimize(lambda q:objective(q)[0],initial,jac=lambda q:objective(q)[1],method='SLSQP',bounds=list(zip(lo,hi)),constraints=[dict(type='ineq',fun=lambda q:constraints(q)[0],jac=lambda q:constraints(q)[1])],options=dict(maxiter=40,ftol=1e-10));initial=polished.x;native=geometry(initial);ok,_,_,_=acceptable(native)
                if ok:break
                pairs.update(native);ordered=sorted(pairs)
        native=geometry(initial);position=max(float(np.linalg.norm(data.xpos[b]-palm_positions[k])) for k,b in enumerate(self.palms));orientation=max(float(np.linalg.norm(Rotation.from_matrix(data.xmat[b].reshape(3,3)@palm_rotations[k].T).as_rotvec())) for k,b in enumerate(self.palms));bad=[]
        for (a,b),(distance,_,_) in native.items():
            limit=-self.plan['target_hand_penetration_m'] if {self.roles[a],self.roles[b]}=={'hand','object'} else -1e-6
            if distance<limit-1e-6:bad.append(dict(pair=[self.names[a],self.names[b]],distance=distance,minimum=limit))
        command=posture_by_pin.copy();command[self.upper]=initial;passed=not bad and position<=self.plan['palm_position_tolerance_m'] and orientation<=self.plan['palm_rotation_tolerance_rad']
        if passed:self.last=initial.copy()
        return command,dict(passed=passed,palm_position_error=position,palm_rotation_error=orientation,violations=bad,optimizer_evaluations=int(opt.nfev),optimizer_success=bool(opt.success),qpos=data.qpos.copy())
