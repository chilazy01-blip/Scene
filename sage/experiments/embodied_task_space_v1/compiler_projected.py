"""Task-space phase optimization with independent exact-grid qualification."""
import time
import numpy as np
from scipy import sparse
import osqp
import mujoco
from .basis import matrices,stopping_weights,embed
from .feasible_projection import restore
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import reserve,trajectory
from sage.experiments.embodied_geometry_feasibility_v1.waypoint_path import interpolate_state
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner,collision_roles
from sage.experiments.embodied_reference_governor_v3.task_planner import RestoringDistanceLimit

class Source:
    def __init__(self,c,qpos,goals,hands,active,residual):
        self.c=c;self.qpos=qpos;self.goals=goals;self.hands=hands
        self.active=active;self.residual=residual;self.rows=len(qpos)-1
    def at(self,p):
        x=np.clip(p,0,1)*self.rows;i=int(np.floor(x));k=min(i+1,self.rows);f=x-i
        return interpolate_state(self.qpos[i],self.qpos[k],f),(1-f)*self.goals[i]+f*self.goals[k],(1-f)*self.hands[i]+f*self.hands[k]
    def derivative(self,p,reference):
        lo=max(0.,p-1e-5);hi=min(1.,p+1e-5)
        left,gl,hl=self.at(lo);right,gr,hr=self.at(hi)
        left[self.c.qpos[self.active]]=reference+self.residual
        right[self.c.qpos[self.active]]=reference+self.residual
        v=np.zeros(self.c.m.nv);mujoco.mj_differentiatePos(self.c.m,v,hi-lo,left,right)
        return v,(gr-gl)/(hi-lo),(hr-hl)/(hi-lo)

class Compiler:
    def __init__(self,c,active,residual,spec):
        self.c=c;self.active=active;self.residual=residual;self.spec=spec;self.j=int(active.sum())
        self.planner=ArmPlanner(c);self.qadr=c.qpos[active];self.dadr=c.qvel[active];self.hand=c.hand[active]
        self.lower=np.maximum(c.lower[active],c.lower[active]-.03-residual)
        self.upper=np.minimum(c.upper[active],c.upper[active]+.03-residual)
    def audit(self,coeff,mat,source,initial,grasp):
        n=len(mat['basis']);ref=(mat['Q']@coeff).reshape(n,self.j);progress=mat['P']@coeff
        vel=(mat['V']@coeff+mat['vb']).reshape(n,self.j);acc=(mat['A']@coeff+mat['ab']).reshape(n,self.j)
        qs=[];goals=[];hands=[];errors=[];badrows=[];stops=[];stop_count=0;stop_native=0.
        for k in range(n):
            q,g,h=source.at(progress[k]);q[self.qadr]=ref[k]+self.residual;self.c.d.qpos[:]=q
            bad,_=collision_roles(self.c,self.c.d,grasp)
            if bad:badrows.append(dict(tick=k,bad=bad))
            errors.append([np.linalg.norm(self.c.d.geom_xpos[self.c.m.geom('gripper0_'+side+'_g0_col').id]-g[i]) for i,side in enumerate(['left','right'])])
            qs.append(q);goals.append(g);hands.append(h)
            for ss,future in enumerate(trajectory(ref[k],vel[k])):
                stop_count+=1;stop_native=max(stop_native,float(np.max(self.lower-future)),float(np.max(future-self.upper)))
                forecast=q.copy();forecast[self.qadr]=future+self.residual;self.c.d.qpos[:]=forecast;sb,_=collision_roles(self.c,self.c.d,grasp)
                if sb:stops.append(dict(tick=k,step=ss+1,bad=sb))
        native=max(0.,float(np.max(self.lower-ref)),float(np.max(ref-self.upper)))
        errors=np.array(errors);hands=np.array(hands);he=float(np.max(abs(ref[-25:,self.hand]+self.residual[self.hand]-hands[-25:,self.hand])))
        pe=float(errors[-25:].max());rate=float(abs(vel).max());aa=float(abs(acc).max());speed=float(abs(vel[-25:]).max())
        excess=max(0.,float(-progress.min()),float(progress.max()-1),float(-np.diff(np.r_[0.,progress]).min()),float(np.diff(np.r_[0.,progress]).max()-1/source.rows),float(abs(progress[-25:]-1).max()))
        passed=not badrows and not stops and stop_native<=2e-8 and native<=2e-8 and rate<=.35+2e-7 and aa<=.5+2e-6 and pe<=.006 and he<=.012 and speed<=.08+2e-7 and excess<=2e-8
        meta=dict(passed=bool(passed),states=n,current_bad=len(badrows),stop_bad=len(stops),stop_states=stop_count,native_excess=native,stop_native_excess=stop_native,max_speed=rate,max_acceleration=aa,endpoint_speed=speed,endpoint_palm_error=pe,endpoint_hand_error=he,phase_excess=excess,current_examples=badrows[:5],stop_examples=stops[:5])
        arrays=dict(reference=ref,progress=progress,velocity=vel,acceleration=acc,qpos=np.array(qs),goals=np.array(goals),hand_goals=hands,errors=errors,initial=initial,active=self.active,residual=self.residual,coefficients=coeff,basis=mat['basis'])
        return meta,arrays,badrows,stops
    def solve(self,source,initial,initial_velocity,n,grasp,callback,deadline):
        # This candidate uses rest endpoints. Incoming history is checked, never reset.
        assert np.max(abs(initial_velocity))<1e-8
        mat=matrices(n,source.rows,self.j,initial,initial_velocity);nk=mat['nk'];width=self.j+1;size=nk*width
        anchor=np.empty((nk,width))
        for k,p in enumerate(mat['greville']):
            q,_,_=source.at(p);anchor[k,:self.j]=q[self.qadr]-self.residual;anchor[k,-1]=p
        anchor[:3,:self.j]=initial;anchor[-3:,:self.j]=anchor[-1,:self.j];anchor=anchor.ravel()
        Q,P,V,A=mat['Q'],mat['P'],mat['V'],mat['A'];vb,ab=mat['vb'],mat['ab'];K,off=reserve()
        hard=[Q,V,A,Q+K*.02*V,P,mat['DP']]
        lows=[np.tile(self.lower,n),np.full(n*self.j,-.35)-vb,np.full(n*self.j,-.5)-ab,np.tile(self.lower,n)-off-K*.02*vb,np.zeros(n),np.zeros(n)]
        highs=[np.tile(self.upper,n),np.full(n*self.j,.35)-vb,np.full(n*self.j,.5)-ab,np.tile(self.upper,n)+off-K*.02*vb,np.ones(n),np.full(n,1/source.rows)]
        eq=[];rhs=[]
        for k in range(3):
            for j in range(self.j):
                row=np.zeros(size);row[k*width+j]=1;eq.append(row);rhs.append(initial[j])
        for k in [nk-3,nk-2]:
            for j in range(self.j):
                row=np.zeros(size);row[k*width+j]=1;row[(nk-1)*width+j]=-1;eq.append(row);rhs.append(0.)
        for k,value in [(0,0.),(nk-1,1.)]:
            row=np.zeros(size);row[k*width+self.j]=1;eq.append(row);rhs.append(value)
        hard.append(sparse.csr_matrix(np.array(eq)));lows.append(np.array(rhs));highs.append(np.array(rhs))
        hard=sparse.vstack(hard,format='csr');lo=np.concatenate(lows);hi=np.concatenate(highs)
        # Exact elimination of fixed and equal coefficients. No scientific constraint is relaxed.
        er=[];ec=[];variable_rows=[]
        for k in range(3,nk-2):
            for j in range(self.j):
                index=len(variable_rows);variable_rows.append(k*width+j)
                for kk in ([k] if k<nk-3 else [nk-3,nk-2,nk-1]):er.append(kk*width+j);ec.append(index)
        for k in range(1,nk-1):
            index=len(variable_rows);variable_rows.append(k*width+self.j);er.append(k*width+self.j);ec.append(index)
        E=sparse.csr_matrix((np.ones(len(er)),(er,ec)),shape=(size,len(variable_rows)))
        reduced=E.shape[1];hard_reduced=hard@E
        nonzero=np.diff(hard_reduced.indptr)>0
        fixed_residual=max(0.,float(np.max(lo[~nonzero]-(hard@anchor)[~nonzero],initial=0)),float(np.max((hard@anchor)[~nonzero]-hi[~nonzero],initial=0)))
        if fixed_residual>2e-8:raise ValueError('fixed_coefficient_constraint_residual')
        hard_reduced=hard_reduced[nonzero]

        limits=[RestoringDistanceLimit(v) for v in [self.planner.self_limit,self.planner.support_limit,self.planner.object_limits[grasp]]]
        if grasp:limits.append(RestoringDistanceLimit(self.planner.grasp_limit))
        selected=set(range(0,n,self.spec['search_stride']))|{n-26,n-25,n-1};stop_selected=set();records=[];last=None
        for iteration in range(self.spec['max_iterations']):
            if time.monotonic()>=deadline:break
            ref=(Q@anchor).reshape(n,self.j);progress=P@anchor;vel=(V@anchor+vb).reshape(n,self.j)
            Jrows=[];errors=[];geometry=[];bounds=[]
            for tick in sorted(selected):
                p=float(np.clip(progress[tick],0,1));q,goal,hand=source.at(p);q[self.qadr]=ref[tick]+self.residual
                self.planner.config.update(q);dv,dgoal,dhand=source.derivative(p,ref[tick]);b=mat['basis'][tick];qw=np.tile(b[:,None],(1,self.j));jac=[];err=[]
                for i,side in enumerate(['left','right']):
                    gid=self.c.m.geom('gripper0_'+side+'_g0_col').id;jp=np.zeros((3,self.c.m.nv));mujoco.mj_jacGeom(self.c.m,self.planner.config.data,jp,None,gid)
                    jac.append(np.c_[jp[:,self.dadr],jp@dv-dgoal[i]]);err.append(self.planner.config.data.geom_xpos[gid]-goal[i])
                weight=10. if tick>=n-25 else 1.;task=embed(np.vstack(jac),qw,b);error=np.concatenate(err)
                Jrows.append(weight*task);errors.append(weight*error)
                if tick>=n-25:
                    geometry.extend([task,-task]);bounds.extend([np.full(6,.0035)-error,np.full(6,.0035)+error])
                hj=np.c_[np.eye(self.j)[self.hand],-dhand[self.hand]];he=ref[tick,self.hand]+self.residual[self.hand]-hand[self.hand]
                htask=embed(hj,qw,b);Jrows.append(.3*htask);errors.append(.3*he)
                if tick>=n-25:geometry.extend([htask,-htask]);bounds.extend([np.full(int(self.hand.sum()),.010)-he,np.full(int(self.hand.sum()),.010)+he])
                targets=[0]+sorted(ss for tt,ss in stop_selected if tt==tick);futures=trajectory(ref[tick],vel[tick]) if len(targets)>1 else []
                for ss in targets:
                    if ss>len(futures):continue
                    forecast=q.copy();weights=qw
                    if ss:
                        forecast[self.qadr]=futures[ss-1]+self.residual;weights=stopping_weights(mat['basis'],tick,vel[tick],ss)
                    self.planner.config.update(forecast)
                    for limit in limits:
                        z=limit.compute_qp_inequalities(self.planner.config,1.)
                        if z.G is None:continue
                        geometry.append(embed(np.c_[z.G[:,self.dadr],z.G@dv],weights,b));bounds.append(z.h/limit.base.gain)
            geom=sparse.vstack(geometry,format='csr');gh=np.concatenate(bounds);J=sparse.vstack(Jrows,format='csr');e=np.concatenate(errors)
            hess=J.T@J/max(1,len(selected))+1e-5*sparse.eye(size,format='csr');f=np.asarray(J.T@e).ravel()/max(1,len(selected))
            small_geom=geom@E
            lhs=sparse.vstack([sparse.hstack([hard_reduced,sparse.csr_matrix((hard_reduced.shape[0],1))]),sparse.hstack([small_geom,-np.ones((geom.shape[0],1))]),sparse.eye(reduced+1)],format='csc')
            trust=self.spec['initial_trust_rad'] if iteration==0 else self.spec['trust_rad']
            low=np.r_[(lo-hard@anchor)[nonzero],np.full(len(gh),-np.inf),np.full(reduced,-trust),0.]
            high=np.r_[(hi-hard@anchor)[nonzero],gh,np.full(reduced,trust),np.inf]
            small_hess=E.T@hess@E;small_f=np.asarray(E.T@f).ravel()
            solver=osqp.OSQP();solver.setup(P=sparse.block_diag((small_hess,sparse.csc_matrix([[1.]])),format='csc'),q=np.r_[small_f,10.],A=lhs,l=low,u=high,verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=30000,polishing=True,time_limit=min(self.spec['qp_seconds'],max(.01,deadline-time.monotonic())))
            witness=np.zeros(reduced)
            if iteration==0:
                constant=np.tile(np.r_[initial,0.],(nk,1));constant[:,-1]=mat['greville']
                witness=(constant.ravel()-anchor)[variable_rows]
            slack=max(0.,float(np.max(small_geom@witness-gh)))+1e-8
            solver.warm_start(x=np.r_[witness,slack])
            ans=solver.solve();info=dict(status=ans.info.status,iterations=int(ans.info.iter),variables=reduced+1,original_variables=size+1,rows=lhs.shape[0],objective=float(ans.info.obj_val),solver_seconds=float(ans.info.run_time))
            if hasattr(callback,'problem'):callback.problem(iteration,lhs,low,high,ans.x,E,anchor)
            if ans.x is None or not np.isfinite(ans.x).all():
                callback(iteration,dict(solver=info,status='numerical_unknown'),None);records.append(info);break
            original_residual=max(0.,float(np.max(low-lhs@ans.x)),float(np.max(lhs@ans.x-high)))
            new=anchor+E@ans.x[:-1];hard_error=max(0.,float(np.max(lo-hard@new)),float(np.max(hard@new-hi)))
            info.update(hard_residual=hard_error,complete_qp_residual=original_residual,search_slack=float(ans.x[-1]),optimal=ans.info.status_val==1)
            if hard_error>2e-7 or original_residual>2e-7:
                info['pre_restoration_hard_residual']=hard_error
                corrected,restoration=restore(lhs,low,high,ans.x,min(10.,max(.01,deadline-time.monotonic())))
                info['restoration']=restoration
                if corrected is not None:
                    new=anchor+E@corrected[:-1]
                    hard_error=max(0.,float(np.max(lo-hard@new)),float(np.max(hard@new-hi)))
                    original_residual=max(0.,float(np.max(low-lhs@corrected)),float(np.max(lhs@corrected-high)))
                    info.update(hard_residual=hard_error,complete_qp_residual=original_residual,search_slack=float(corrected[-1]))
            if hard_error>2e-7 or original_residual>2e-7:
                callback(iteration,dict(solver=info,status='primal_residual_rejected'),None);records.append(info);break
            meta,arrays,bad,stops=self.audit(new,mat,source,initial,grasp)
            callback(iteration,dict(solver=info,geometry=meta),arrays);records.append(dict(solver=info,geometry=meta));last=(meta,arrays)
            if meta['passed']:return dict(passed=True,iterations=records),arrays
            selected.update(row['tick'] for row in bad);stop_selected.update((row['tick'],row['step']) for row in stops);selected.update(row['tick'] for row in stops);anchor=new
        return dict(passed=False,iterations=records,reason='bounded_search_without_qualified_path' if last else 'numerical_unknown'),None if last is None else last[1]
