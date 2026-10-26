"""Same joint method with complete-row LP primal restoration and saved-solve recovery."""
import time
import numpy as np
from scipy import sparse
import osqp
from .joint_compiler import Compiler as Base
from .joint_exchange import initial_hard_rows,violated_rows
from sage.experiments.embodied_task_space_v1.feasible_projection import restore

def augment(selected,stop_selected,bad,stops):
    selected.update(v['tick'] for v in bad);worst={}
    for v in stops:
        severity=max(q['penetration_m'] for q in v['violations'])
        if v['tick'] not in worst or severity>worst[v['tick']][0]:worst[v['tick']]=(severity,v['step'])
    stop_selected.update((k,v[1]) for k,v in worst.items());selected.update(worst)

class Compiler(Base):
    def solve(self,callback,deadline):
        self.audit_deadline=deadline;m=self.map;x,initialization=m.source_anchor(self.qadr,self.residual);selected=set(range(0,m.n,self.spec['search_stride']));stop_selected=set();hard_selected=initial_hard_rows(m,self.spec['hard_stride']);records=[];last=None;start_iteration=0
        for a,b in zip(m.offsets[:-1],m.offsets[1:]):selected.update([int(a),int(b-26),int(b-25),int(b-1)])
        callback('initialization',dict(**initialization,all_hard_rows=m.hard.shape[0],initial_selected_hard_rows=len(hard_selected)),None)
        resumed=getattr(self,'resumed_primal',None)
        if resumed is not None:
            x=resumed['variables'].copy();assert m.residual(x)<=1e-8
            try:meta,arrays,bad,stops=self.audit(x)
            except TimeoutError:
                callback(0,dict(status='full_grid_audit_case_deadline',recovered_saved_primal=True),None)
                if hasattr(callback,'provisional'):callback.provisional(0,x)
                return dict(passed=False,reason='bounded_case_audit_deadline',iterations=records),None
            r=dict(solver=dict(recovered_saved_primal=True,full_hard_residual=m.residual(x),source=resumed['source']),geometry=meta);callback(0,r,arrays);records.append(r);last=(meta,arrays);start_iteration=1
            if meta['passed']:return dict(passed=True,iterations=records),arrays
            augment(selected,stop_selected,bad,stops)
        for iteration in range(start_iteration,self.spec['max_iterations']):
            if time.monotonic()>=deadline:break
            t=time.monotonic();J,e,G,h=self.linearize(x,selected,stop_selected);linear_seconds=time.monotonic()-t;size=m.size
            H=J.T@J/max(1,len(selected))+1e-5*sparse.eye(size,format='csr');f=np.asarray(J.T@e).ravel()/max(1,len(selected));trust=self.spec['initial_trust_rad'] if iteration==0 else self.spec['trust_rad'];ids=np.array(sorted(hard_selected));hard=m.hard[ids];value=hard@x
            tail=sparse.vstack([sparse.hstack([G,-np.ones((G.shape[0],1))]),sparse.eye(size+1)],format='csr');tail_low=np.r_[np.full(len(h),-np.inf),np.full(size,-trust),0.];tail_high=np.r_[h,np.full(size,trust),np.inf]
            lhs=sparse.vstack([sparse.hstack([hard,sparse.csr_matrix((len(ids),1))]),tail],format='csc');lo=np.r_[m.low[ids]-value,tail_low];hi=np.r_[m.high[ids]-value,tail_high]
            solver=osqp.OSQP();solver.setup(P=sparse.block_diag((H,sparse.csc_matrix([[1.]])),format='csc'),q=np.r_[f,10.],A=lhs,l=lo,u=hi,verbose=False,eps_abs=1e-8,eps_rel=1e-8,max_iter=30000,polishing=True,time_limit=min(self.spec['qp_seconds'],max(.01,deadline-time.monotonic())))
            slack=max(0.,float(-h.min(initial=0)))+1e-8;solver.warm_start(x=np.r_[np.zeros(size),slack]);ans=solver.solve();info=dict(status=ans.info.status,status_val=int(ans.info.status_val),iterations=int(ans.info.iter),variables=size+1,rows=lhs.shape[0],full_hard_rows=m.hard.shape[0],linear_seconds=linear_seconds,solver_seconds=float(ans.info.run_time),optimal=ans.info.status_val==1)
            if ans.x is None or not np.isfinite(ans.x).all():r=dict(status='no_finite_primal',solver=info);callback(iteration,r,None);records.append(r);break
            primal=ans.x.copy();residual=max(0.,float(np.max(lo-lhs@primal)),float(np.max(lhs@primal-hi)));new=x+primal[:-1];violations,full_residual=violated_rows(m,new);hard_selected.update(violations)
            if max(residual,full_residual)>1e-8:
                all_value=m.hard@x;full=sparse.vstack([sparse.hstack([m.hard,sparse.csr_matrix((m.hard.shape[0],1))]),tail],format='csr');all_lo=np.r_[m.low-all_value,tail_low];all_hi=np.r_[m.high-all_value,tail_high]
                info.update(pre_restoration_selected_residual=residual,pre_restoration_full_residual=full_residual)
                fixed,repair=restore(full,all_lo,all_hi,primal,min(60.,max(.01,deadline-time.monotonic())));info['full_row_restoration']=repair
                if fixed is not None:
                    primal=fixed;new=x+primal[:-1];residual=max(0.,float(np.max(all_lo-full@primal)),float(np.max(full@primal-all_hi)));_,full_residual=violated_rows(m,new)
                if max(residual,full_residual)>1e-8 and hasattr(callback,'problem'):callback.problem(iteration,0,full,all_lo,all_hi,primal,x,H,f,np.arange(m.hard.shape[0]))
            info.update(complete_qp_residual=residual,full_hard_residual=full_residual)
            if max(residual,full_residual)>1e-8:r=dict(status='numerical_unknown_full_primal_unqualified',solver=info);callback(iteration,r,None);records.append(r);break
            try:meta,arrays,bad,stops=self.audit(new)
            except TimeoutError:
                r=dict(status='full_grid_audit_case_deadline',solver=info);callback(iteration,r,None);records.append(r)
                if hasattr(callback,'provisional'):callback.provisional(iteration,new)
                break
            r=dict(solver=info,geometry=meta);callback(iteration,r,arrays);records.append(r);last=(meta,arrays)
            if meta['passed']:return dict(passed=True,iterations=records),arrays
            augment(selected,stop_selected,bad,stops);x=new
        return dict(passed=False,iterations=records,reason='bounded_joint_search_without_qualified_path' if last else 'numerical_unknown'),None if last is None else last[1]
    def audit(self,x):
        m=self.map;raw,progress,rawv,rawa=m.values(x);ref=np.clip(raw,self.lower,self.upper);change=float(abs(ref-raw).max());velocity=np.diff(np.vstack([m.initial,ref]),axis=0)/.02;acc=np.diff(np.vstack([m.incoming,velocity]),axis=0)/.02
        qpos=[];goals=[];hands=[];errors=[];bad=[];stops=[];metas=[];previous_q=None
        for i,(stage,_,_) in enumerate(self.stages):
            start,end=map(int,m.offsets[i:i+2]);grasp=stage in GRASP;s=self.sources[i];stop_count=0;stop_native=0.;local_bad=[];local_stops=[]
            if previous_q is not None:
                boundary=s.at(0.)[0];boundary[self.qadr]=ref[start-1]+self.residual;assert abs(boundary-previous_q).max()<1e-9,'body_phase_boundary_discontinuity'
            for tick in range(start,end):
                if tick%50==0 and time.monotonic()>=self.audit_deadline:raise TimeoutError('audit_case_deadline')
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
