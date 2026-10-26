"""Joint task-space optimization. Every phase endpoint remains a shared variable."""
import time
import numpy as np
from scipy import sparse
import osqp,mujoco
from .joint_map import JointMap
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner,collision_roles
from sage.experiments.embodied_reference_governor_v3.task_planner import RestoringDistanceLimit
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import trajectory
from sage.experiments.embodied_task_space_v1.feasible_projection import restore

GRASP={'close','rise_lift','carry','stop_target','lower_place','release'}
class Compiler:
    def __init__(self,c,active,residual,sources,stages,spec):
        self.c=c;self.active=active;self.residual=residual;self.sources=sources;self.stages=stages;self.spec=spec;self.j=int(active.sum());self.qadr=c.qpos[active];self.dadr=c.qvel[active];self.hand=c.hand[active]
        self.lower=np.maximum(c.lower[active],c.lower[active]-.03-residual);self.upper=np.minimum(c.upper[active],c.upper[active]+.03-residual)
        self.map=JointMap(sources,[b-a for _,a,b in stages],c.nominal[active],np.zeros(self.j),self.lower,self.upper)
        self.planner=ArmPlanner(c);p=self.planner
        self.limits={g:[RestoringDistanceLimit(v) for v in [p.self_limit,p.support_limit,p.object_limits[g]]+([p.grasp_limit] if g else [])] for g in [False,True]}
        self.phase_of=np.repeat(np.arange(len(stages)),np.diff(self.map.offsets));self.local=np.concatenate([np.arange(n) for n in np.diff(self.map.offsets)])
    def linearize(self,x,selected,stop_selected):
        m=self.map;ref,progress,vel,acc=m.values(x);objectives=[];errors=[];rows=[];bounds=[];stops_by={}
        for tick,step in stop_selected:stops_by.setdefault(tick,[]).append(step)
        for tick in sorted(selected):
            i=int(self.phase_of[tick]);s=self.sources[i];grasp=self.stages[i][0] in GRASP;terminal=tick>=m.offsets[i+1]-25;p=float(np.clip(progress[tick],0,1));q,goal,hand=s.at(p);q[self.qadr]=ref[tick]+self.residual
            self.planner.config.update(q);dv,dgoal,dhand=s.derivative(p,ref[tick]);jac=[];err=[]
            for k,side in enumerate(['left','right']):
                gid=self.c.m.geom('gripper0_'+side+'_g0_col').id;jp=np.zeros((3,self.c.m.nv));mujoco.mj_jacGeom(self.c.m,self.planner.config.data,jp,None,gid)
                jac.append(np.c_[jp[:,self.dadr],jp@dv-dgoal[k]]);err.append(self.planner.config.data.geom_xpos[gid]-goal[k])
            task=m.embed(np.vstack(jac),tick);error=np.concatenate(err);weight=10. if terminal else 1.
            objectives.append(weight*task);errors.append(weight*error)
            if terminal:rows.extend([task,-task]);bounds.extend([np.full(6,.0035)-error,np.full(6,.0035)+error])
            hj=np.c_[np.eye(self.j)[self.hand],-dhand[self.hand]];he=ref[tick,self.hand]+self.residual[self.hand]-hand[self.hand];ht=m.embed(hj,tick)
            objectives.append(.3*ht);errors.append(.3*he)
            if terminal:rows.extend([ht,-ht]);bounds.extend([np.full(int(self.hand.sum()),.010)-he,np.full(int(self.hand.sum()),.010)+he])
            future=trajectory(ref[tick],vel[tick]) if tick in stops_by else []
            for ss in [0]+sorted(stops_by.get(tick,[])):
                if ss>len(future):continue
                forecast=q.copy()
                if ss:forecast[self.qadr]=future[ss-1]+self.residual
                self.planner.config.update(forecast)
                for limit in self.limits[grasp]:
                    z=limit.compute_qp_inequalities(self.planner.config,1.)
                    if z.G is not None:
                        rows.append(m.embed(np.c_[z.G[:,self.dadr],z.G@dv],tick,vel[tick],ss));bounds.append(z.h/limit.base.gain)
        return sparse.vstack(objectives,format='csr'),np.concatenate(errors),sparse.vstack(rows,format='csr'),np.concatenate(bounds)
    def audit(self,x):
        m=self.map;raw,progress,rawv,rawa=m.values(x);ref=np.clip(raw,self.lower,self.upper);change=float(abs(ref-raw).max());velocity=np.diff(np.vstack([m.initial,ref]),axis=0)/.02;acc=np.diff(np.vstack([m.incoming,velocity]),axis=0)/.02
        qpos=[];goals=[];hands=[];errors=[];bad=[];stops=[];metas=[];previous_q=None
        for i,(stage,_,_) in enumerate(self.stages):
            start,end=map(int,m.offsets[i:i+2]);grasp=stage in GRASP;s=self.sources[i];stop_count=0;stop_native=0.;local_bad=[];local_stops=[]
            if previous_q is not None:
                boundary=s.at(0.)[0];boundary[self.qadr]=ref[start-1]+self.residual;assert abs(boundary-previous_q).max()<1e-9,'body_phase_boundary_discontinuity'
            for tick in range(start,end):
                q,g,h=s.at(progress[tick]);q[self.qadr]=ref[tick]+self.residual;self.c.d.qpos[:]=q;b,_=collision_roles(self.c,self.c.d,grasp)
                if b:local_bad.append(dict(tick=tick,violations=b))
                errors.append([np.linalg.norm(self.c.d.geom_xpos[self.c.m.geom('gripper0_'+side+'_g0_col').id]-g[k]) for k,side in enumerate(['left','right'])]);qpos.append(q);goals.append(g);hands.append(h)
                for ss,future in enumerate(trajectory(ref[tick],velocity[tick])):
                    fq=q.copy();fq[self.qadr]=future+self.residual;self.c.d.qpos[:]=fq;b,_=collision_roles(self.c,self.c.d,grasp);stop_count+=1;stop_native=max(stop_native,float(np.max(self.lower-future)),float(np.max(future-self.upper)))
                    if b:local_stops.append(dict(tick=tick,step=ss+1,violations=b))
            prev=np.r_[0.,progress[start:end]];phase=max(0.,float(-prev.min()),float(prev.max()-1),float(-np.diff(prev).min()),float(np.diff(prev).max()-1/s.rows),float(abs(progress[end-25:end]-1).max()))
            palm=float(np.max(errors[end-25:end]));he=float(abs(ref[end-25:end,self.hand]+self.residual[self.hand]-np.asarray(hands[end-25:end])[:,self.hand]).max());speed=float(abs(velocity[start:end]).max());aa=float(abs(acc[start:end]).max());endspeed=float(abs(velocity[end-25:end]).max());exact=bool(np.all(ref[start:end]>=self.lower) and np.all(ref[start:end]<=self.upper))
            passed=exact and change<=2e-8 and not local_bad and not local_stops and stop_native<=2e-8 and speed<=.35+2e-7 and aa<=.5+2e-6 and endspeed<=.08+2e-7 and palm<=.006 and he<=.012 and phase<=2e-8
            metas.append(dict(stage=stage,passed=bool(passed),states=end-start,stop_states=stop_count,current_bad=len(local_bad),stop_bad=len(local_stops),stop_native_excess=stop_native,max_speed=speed,max_acceleration=aa,endpoint_speed=endspeed,endpoint_palm_error=palm,endpoint_hand_error=he,phase_excess=phase));bad.extend(local_bad);stops.extend(local_stops);previous_q=qpos[-1]
        meta=dict(passed=all(v['passed'] for v in metas),states=m.n,stop_states=sum(v['stop_states'] for v in metas),current_bad=len(bad),stop_bad=len(stops),max_representation_change_rad=change,phases=metas)
        arrays=dict(reference=ref,raw_reference=raw,progress=progress,velocity=velocity,acceleration=acc,raw_velocity=rawv,raw_acceleration=rawa,qpos=np.array(qpos),goals=np.array(goals),hand_goals=np.array(hands),errors=np.array(errors),initial=m.initial,initial_velocity=m.incoming,active=self.active,residual=self.residual,variables=x,offsets=m.offsets)
        return meta,arrays,bad,stops
    def solve(self,callback,deadline):
        m=self.map;x,initialization=m.source_anchor(self.qadr,self.residual);selected=set(range(0,m.n,self.spec['search_stride']));stop_selected=set();records=[];last=None
        for start,end in zip(m.offsets[:-1],m.offsets[1:]):selected.update([int(start),int(end-26),int(end-25),int(end-1)])
        callback('initialization',initialization,None)
        for iteration in range(self.spec['max_iterations']):
            if time.monotonic()>=deadline:break
            t=time.monotonic();J,e,G,h=self.linearize(x,selected,stop_selected);linear_seconds=time.monotonic()-t
            size=m.size;H=J.T@J/max(1,len(selected))+1e-5*sparse.eye(size,format='csr');f=np.asarray(J.T@e).ravel()/max(1,len(selected));trust=self.spec['initial_trust_rad'] if iteration==0 else self.spec['trust_rad']
            lhs=sparse.vstack([sparse.hstack([m.hard,sparse.csr_matrix((m.hard.shape[0],1))]),sparse.hstack([G,-np.ones((G.shape[0],1))]),sparse.eye(size+1)],format='csc')
            value=m.hard@x;lo=np.r_[m.low-value,np.full(len(h),-np.inf),np.full(size,-trust),0.];hi=np.r_[m.high-value,h,np.full(size,trust),np.inf]
            solver=osqp.OSQP();solver.setup(P=sparse.block_diag((H,sparse.csc_matrix([[1.]])),format='csc'),q=np.r_[f,10.],A=lhs,l=lo,u=hi,verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=30000,polishing=True,time_limit=min(self.spec['qp_seconds'],max(.01,deadline-time.monotonic())))
            slack=max(0.,float(-h.min(initial=0)))+1e-8;solver.warm_start(x=np.r_[np.zeros(size),slack]);ans=solver.solve();info=dict(status=ans.info.status,status_val=int(ans.info.status_val),iterations=int(ans.info.iter),variables=size+1,rows=lhs.shape[0],linear_seconds=linear_seconds,solver_seconds=float(ans.info.run_time),optimal=ans.info.status_val==1)
            if ans.x is None or not np.isfinite(ans.x).all():callback(iteration,dict(solver=info,status='numerical_unknown'),None);records.append(info);break
            residual=max(0.,float(np.max(lo-lhs@ans.x)),float(np.max(lhs@ans.x-hi)));new=x+ans.x[:-1];hard=m.residual(new)
            if max(hard,residual)>1e-8:
                fixed,repair=restore(lhs,lo,hi,ans.x,min(self.spec['primal_restore_seconds'],max(.01,deadline-time.monotonic())));info['restoration']=repair
                if fixed is not None:ansx=fixed;new=x+ansx[:-1];hard=m.residual(new);residual=max(0.,float(np.max(lo-lhs@ansx)),float(np.max(lhs@ansx-hi)))
            info.update(hard_residual=hard,complete_qp_residual=residual)
            if max(hard,residual)>1e-8:callback(iteration,dict(solver=info,status='primal_residual_rejected'),None);records.append(info);break
            meta,arrays,bad,stops=self.audit(new);r=dict(solver=info,geometry=meta);callback(iteration,r,arrays);records.append(r);last=(meta,arrays)
            if meta['passed']:return dict(passed=True,iterations=records),arrays
            selected.update(v['tick'] for v in bad)
            # Add the worst observed stop of each failing tick; every stop is still audited.
            worst={}
            for v in stops:
                severity=max(q['penetration_m'] for q in v['violations'])
                if v['tick'] not in worst or severity>worst[v['tick']][0]:worst[v['tick']]=(severity,v['step'])
            stop_selected.update((k,v[1]) for k,v in worst.items());selected.update(worst);x=new
        return dict(passed=False,iterations=records,reason='bounded_joint_search_without_qualified_path' if last else 'numerical_unknown'),None if last is None else last[1]
