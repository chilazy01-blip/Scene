"""Jointly choose upper reference increments and a body-path progress fraction.

This is a private kinematic planning hypothesis. It never updates simulator
state and does not certify physical body tracking or stopping delay.
"""
import copy
import numpy as np
import mujoco
import mink
import qpsolvers
from scipy.optimize import linprog
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner,collision_roles
from sage.experiments.embodied_reference_governor_v3.task_planner import RestoringDistanceLimit
from sage.experiments.embodied_reference_governor_v1.governor import Proposal,ReferenceRejected

class CoupledProgressPlanner:
    def __init__(self,context,governor):
        self.c=context;self.g=governor;self.base=ArmPlanner(context);self.active=np.flatnonzero(governor.active);self.attempts=0
        self.limits=[RestoringDistanceLimit(self.base.self_limit),RestoringDistanceLimit(self.base.support_limit)]
        self.object_limits={k:RestoringDistanceLimit(v) for k,v in self.base.object_limits.items()};self.grasp_limit=RestoringDistanceLimit(self.base.grasp_limit)
        self.gain=governor.DT*float(np.min(governor.feedback_rate[governor.active]))
    def snapshot(self):return dict(version=1,law='joint_reference_body_progress_heading_v1',governor=self.g.snapshot(),attempts=self.attempts)
    def restore(self,state):
        if set(state)!=set(self.snapshot()) or state['version']!=1 or state['law']!='joint_reference_body_progress_heading_v1' or type(state['attempts']) is not int or state['attempts']<0:raise ReferenceRejected('coupled_checkpoint')
        self.g.restore(copy.deepcopy(state['governor']));self.attempts=state['attempts']
    def _target(self,task,center,rot,local):
        transform=np.eye(4);transform[:3,:3]=rot;transform[:3,3]=center-rot@local;task.set_target(mink.SE3.from_matrix(transform))
    def step(self,tick,measured_qpos,measured_dq,body_preview,centers0,rotations0,hand0,centers1,rotations1,hand1,grasp=False):
        c,g=self.c,self.g;measured=np.asarray(measured_qpos);preview=np.asarray(body_preview)
        if measured.shape!=(c.m.nq,) or preview.shape!=measured.shape or not np.isfinite(measured).all() or not np.isfinite(preview).all():raise ReferenceRejected('coupled_body_shape')
        if type(tick) is not int or tick!=g.next_tick:raise ReferenceRejected('nonsequential_tick')
        if np.max(abs(preview[c.qpos[self.active]]-measured[c.qpos[self.active]]))>1e-12:raise ReferenceRejected('preview_changes_observed_upper')
        before=g.snapshot();lower,upper=g.admissible_bounds(measured[c.qpos],measured_dq);self.base.config.update(measured)
        body_delta=np.zeros(c.m.nv);mujoco.mj_differentiatePos(c.m,body_delta,1.,measured,preview);body_delta[c.qvel[self.active]]=0
        E=np.zeros((c.m.nv,len(self.active)+1));E[c.qvel[self.active],np.arange(len(self.active))]=1;E[:,-1]=body_delta;n=E.shape[1]
        H=1e-5*np.eye(n);f=np.zeros(n)
        for j,task in enumerate(self.base.tasks):
            self._target(task,np.asarray(centers0[j]),np.asarray(rotations0[j]),self.base.local[j]);e0=task.compute_error(self.base.config);jac=task.compute_jacobian(self.base.config)
            self._target(task,np.asarray(centers1[j]),np.asarray(rotations1[j]),self.base.local[j]);e1=task.compute_error(self.base.config)
            A=jac@E;A[:,-1]+=e1-e0;A=task.cost[:,None]*A;error=task.cost*self.gain*e0;H+=A.T@A;f+=A.T@error
        for j,index in enumerate(self.active):
            if not c.hand[index]:continue
            a=np.zeros(n);a[j]=1;a[-1]=-(hand1[index]-hand0[index]);e=self.gain*(measured[c.qpos[index]]-hand0[index]);H+=np.outer(a,a);f+=a*e
        limits=self.limits+[self.object_limits[bool(grasp)]]+([self.grasp_limit] if grasp else [])
        gs=[];hs=[]
        for limit in limits:
            z=limit.compute_qp_inequalities(self.base.config,1.)
            if z.G is not None:gs.append(z.G@E);hs.append(z.h)
        G=np.vstack(gs) if gs else np.zeros((0,n));h=np.concatenate(hs) if hs else np.zeros(0);finite=np.isfinite(h);G,h=G[finite],h[finite]
        residual=measured[c.qpos]-g.reference
        lo=np.maximum(lower[self.active]-g.reference[self.active],c.lower[self.active]-.03+1e-9-measured[c.qpos[self.active]])
        hi=np.minimum(upper[self.active]-g.reference[self.active],c.upper[self.active]+.03-1e-9-measured[c.qpos[self.active]])
        # Prospective heading-frame translation and height bounds.
        # These are not physical motion or stopping certificates.
        body_cap=1.
        w,x,y,z=measured[3:7];yaw=np.arctan2(2*(w*z+x*y),1-2*(y*y+z*z));cy,sy=np.cos(yaw),np.sin(yaw)
        heading_delta=np.array([cy*body_delta[0]+sy*body_delta[1],-sy*body_delta[0]+cy*body_delta[1],body_delta[2]])
        for delta,limit in zip(abs(heading_delta),[.15*.02,.08*.02,.02*.02]):
            if delta>0:body_cap=min(body_cap,limit/delta)
        lower_bound=np.r_[lo,0.];upper_bound=np.r_[hi,body_cap];failures=[]
        for factor in [1.,.5,.25,.125,0.]:
            ub=upper_bound.copy();ub[-1]*=factor;self.attempts+=1
            obj=np.zeros(n);obj[-1]=-1.
            lp=linprog(obj,A_ub=G,b_ub=h,bounds=list(zip(lower_bound,ub)),method='highs',options={'presolve':True})
            if not lp.success:failures.append('linear_infeasible');continue
            alpha=float(np.clip(lp.x[-1],0,ub[-1]));Aeq=np.zeros((1,n));Aeq[0,-1]=1.
            solution=qpsolvers.solve_qp(H,f,G,h,A=Aeq,b=np.array([alpha]),lb=lower_bound,ub=ub,solver='quadprog')
            if solution is None or not np.isfinite(solution).all():failures.append('qp_infeasible');continue
            if len(h) and np.max(G@solution-h)>1e-7:failures.append('constraint_residual');continue
            ref=g.reference.copy();ref[self.active]+=solution[:-1];ref=np.clip(ref,c.lower,c.upper);velocity=(ref-g.reference)/.02
            predicted=(1-alpha)*measured+alpha*preview
            for j in range(c.m.njnt):
                if int(c.m.jnt_type[j])==int(mujoco.mjtJoint.mjJNT_FREE):
                    adr=int(c.m.jnt_qposadr[j])+3;a=measured[adr:adr+4];b=preview[adr:adr+4];b=b if np.dot(a,b)>=0 else -b;q=(1-alpha)*a+alpha*b;predicted[adr:adr+4]=q/np.linalg.norm(q)
            predicted[c.qpos[self.active]]=ref[self.active]+residual[self.active];data=mujoco.MjData(c.m);data.qpos[:]=predicted;bad,_=collision_roles(c,data,grasp)
            if bad:failures.append('nonlinear_geometry');continue
            goals=(1-alpha)*np.asarray(centers0)+alpha*np.asarray(centers1);errors=[float(np.linalg.norm(data.geom_xpos[c.m.geom('gripper0_'+side+'_g0_col').id]-goals[j])) for j,side in enumerate(['left','right'])]
            meta=dict(progress_fraction=alpha,body_fraction_cap=body_cap,position_errors_m=errors,max_reference_speed=float(abs(velocity).max()),max_reference_acceleration=float((abs(velocity-g.velocity)/.02).max()),attempts=self.attempts,rejected_previews=failures,physical_body_tracking_certified=False,private_predicted_qpos=predicted.tolist())
            proposal=Proposal(g._hash(before),tick,tuple(ref),tuple(velocity),meta);reference,info=g.commit(proposal);return reference,info
        raise ReferenceRejected('coupled_progress_infeasible:'+repr(failures))
