"""Contact hierarchy, whole-path incumbent and measured nonlinear step acceptance."""
import time
import numpy as np
import mujoco
from scipy import sparse
from sage.experiments.embodied_task_space_v2.joint_compiler import Compiler as Base,GRASP
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import trajectory
from .globalization_gate import accept_geometry_step
from .linear_solver import solve_lp


class Compiler(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        # These are prospective search margins; final original native gates remain unchanged.
        self.planner.support_limit.minimum_distance_from_collisions=.002
        for v in self.planner.object_limits.values():v.minimum_distance_from_collisions=.002
        self.deadline=float('inf')
    def check_time(self,reserve=0.):
        if time.monotonic()+reserve>=self.deadline:raise TimeoutError('case_process_deadline_reserve')
    def role(self,bad):
        names=bad['geoms'];obj='fb2_box_geom' in names
        if obj and any(n.startswith('gripper0_') for n in names) and bad['allowed_role']:return 3,.005
        if not bad['allowed_role']:
            if any(n in ['fb2_source_top','fb2_target_top'] for n in names):return 1,1e-6
            if obj:return 2,1e-6
            return 0,1e-6
        return 4,.01
    def metrics(self,meta,bad,stops):
        raw=np.zeros((2,self.map.n,5));worst={}
        for kind,items in enumerate([bad,stops]):
            for row in items:
                tick=row['tick']
                for b in row['violations']:
                    role,threshold=self.role(b);v=max(0.,b['penetration_m']-threshold)/.005
                    raw[kind,tick,role]=max(raw[kind,tick,role],v)
                    if kind and ((tick,role) not in worst or v>worst[tick,role][0]):worst[tick,role]=(v,row['step'])
        ends=np.array([[max(0.,r['endpoint_palm_error']/.006-1),max(0.,r['endpoint_hand_error']/.012-1)] for r in meta['phases']])
        vector=np.r_[raw.ravel()/np.sqrt(self.map.n),ends.ravel()/np.sqrt(30)]
        return vector,raw,ends,{(tick,step) for (tick,role),(value,step) in worst.items()}
    def evaluate(self,x):
        self.check_time();meta,arrays,bad,stops=super().audit(x);self.check_time()
        vector,raw,ends,worst=self.metrics(meta,bad,stops);meta['merit']=float(vector@vector)
        return dict(meta=meta,arrays=arrays,bad=bad,stops=stops,vector=vector,raw=raw,ends=ends,worst=worst)
    def linearize_hierarchy(self,x,selected,stop_selected):
        m=self.map;ref,progress,vel,acc=m.values(x);geo=[];bounds=[];true_bounds=[];groups=[];labels=[];descriptors=[];endpoints=[];tracking=[];steps={}
        for tick,step in stop_selected:steps.setdefault(tick,set()).add(step)
        for tick in sorted(selected):
            self.check_time(5.);phase=int(self.phase_of[tick]);s=self.sources[phase];p=float(np.clip(progress[tick],0,1));q,goal,hand=s.at(p);q[self.qadr]=ref[tick]+self.residual;self.planner.config.update(q)
            dv,dgoal,dhand=s.derivative(p,ref[tick]);jac=[];err=[]
            for k,side in enumerate(['left','right']):
                gid=self.c.m.geom('gripper0_'+side+'_g0_col').id;jp=np.zeros((3,self.c.m.nv));mujoco.mj_jacGeom(self.c.m,self.planner.config.data,jp,None,gid)
                jac.append(np.c_[jp[:,self.dadr],jp@dv-dgoal[k]]);err.extend(self.planner.config.data.geom_xpos[gid]-goal[k])
            task=m.embed(np.vstack(jac),tick);error=np.array(err);ht=m.embed(np.c_[np.eye(self.j)[self.hand],-dhand[self.hand]],tick);he=ref[tick,self.hand]+self.residual[self.hand]-hand[self.hand]
            if tick==m.offsets[phase+1]-1:endpoints.append((phase,task,error,ht,he))
            if tick%self.spec['search_stride']==0:tracking.append((phase,task,error))
            future=trajectory(ref[tick],vel[tick]) if tick in steps else []
            grasp=self.stages[phase][0] in GRASP
            for stop in [0]+sorted(steps.get(tick,[])):
                if stop>len(future):continue
                forecast=q.copy()
                if stop:forecast[self.qadr]=future[stop-1]+self.residual
                self.planner.config.update(forecast)
                for role,limit in enumerate(self.limits[grasp]):
                    base=limit.base;jacs=[]
                    for a,b in base.geom_id_pairs:
                        contact=base._compute_contact_with_minimum_distance(self.planner.config.data,a,b)
                        if contact.inactive:continue
                        dg=base.distance_jacobian(self.planner.config.data,contact);jacs.append(-dg)
                        bounds.append(contact.dist-base.minimum_distance_from_collisions);true_bounds.append(contact.dist+(.005 if role==3 else 1e-6))
                        groups.append(phase*4+role);labels.append((int(stop>0)*m.n+tick)*5+role);descriptors.append((tick,stop,role,int(contact.geom1),int(contact.geom2)))
                    if jacs:
                        jj=np.asarray(jacs);geo.append(m.embed(np.c_[jj[:,self.dadr],jj@dv],tick,vel[tick],stop))
        assert len(endpoints)==15
        return dict(G=sparse.vstack(geo,format='csr'),h=np.array(bounds),true_h=np.array(true_bounds),groups=np.array(groups),labels=np.array(labels),descriptors=np.array(descriptors),endpoints=endpoints,tracking=tracking)
    def problem(self,x,linear,trust,contact_caps=None):
        m=self.map;n=m.size;nc=60;nt=30;ni=15;size=n+nc+nt+ni+1;rows=[];lo=[];hi=[]
        def pad(A):return sparse.hstack([A,sparse.csr_matrix((A.shape[0],size-n))],format='csr')
        rows.append(pad(m.hard));v=m.hard@x;lo.append(m.low-v);hi.append(m.high-v)
        G=linear['G'];slack=sparse.coo_matrix((-np.ones(len(linear['h'])),(np.arange(len(linear['h'])),linear['groups'])),shape=(len(linear['h']),nc)).tocsr()
        rows.append(sparse.hstack([G/.005,slack,sparse.csr_matrix((G.shape[0],nt+ni+1))],format='csr'));lo.append(np.full(G.shape[0],-np.inf));hi.append(linear['h']/.005)
        if contact_caps is not None:
            for phase,A,e,B,h in linear['endpoints']:
                for jac,err,scale,tolerance,group in [(A,e,.006,.003,phase*2),(B,h,.012,.010,phase*2+1)]:
                    for sign in [1.,-1.]:
                        z=pad(sign*jac/scale).tolil();z[:,n+nc+group]=-np.ones((len(err),1));rows.append(z.tocsr());lo.append(np.full(len(err),-np.inf));hi.append((tolerance-sign*err)/scale)
            for phase,A,e in linear['tracking']:
                for sign in [1.,-1.]:
                    z=pad(sign*A/.006).tolil();z[:,n+nc+nt+phase]=-np.ones((len(e),1));rows.append(z.tocsr());lo.append(np.full(len(e),-np.inf));hi.append(-sign*e/.006)
            for sign in [1.,-1.]:
                z=pad(sign*sparse.eye(n,format='csr')/trust).tolil();z[:,-1]=-np.ones((n,1));rows.append(z.tocsr());lo.append(np.full(n,-np.inf));hi.append(np.zeros(n))
        rows.append(sparse.eye(size,format='csr'));lo.append(np.r_[np.full(n,-trust),np.zeros(size-n)]);upper=np.r_[np.full(n,trust),np.full(size-n,np.inf)]
        if contact_caps is not None:upper[n:n+nc]=np.maximum(0.,contact_caps)+1e-8
        hi.append(upper);cost=np.zeros(size)
        if contact_caps is None:cost[n:n+nc]=1.
        else:cost[n+nc:n+nc+nt]=1.;cost[n+nc+nt:n+nc+nt+ni]=.01;cost[-1]=.001
        return cost,sparse.vstack(rows,format='csr'),np.concatenate(lo),np.concatenate(hi)
    def predict_vector(self,baseline,linear,delta):
        raw=baseline['raw'].copy().ravel();labels=linear['labels'];raw[np.unique(labels)]=0.
        violation=np.maximum(linear['G']@delta-linear['true_h'],0.)/.005;np.maximum.at(raw,labels,violation)
        ends=baseline['ends'].copy()
        for phase,A,e,B,h in linear['endpoints']:
            ep=(e+A@delta).reshape(2,3);eh=h+B@delta;ends[phase]=[max(0.,float(np.linalg.norm(ep,axis=1).max())/.006-1),max(0.,float(abs(eh).max())/.012-1)]
        return np.r_[raw/np.sqrt(self.map.n),ends.ravel()/np.sqrt(30)]
    def solve(self,x,callback,deadline):
        self.deadline=deadline;current=self.evaluate(x);callback('initial',dict(geometry=current['meta'],initialization='frozen_whole_path_or_source_anchor'),current['arrays']);records=[]
        selected=set(range(0,self.map.n,self.spec['search_stride']))
        selected.update(int(b-1) for b in self.map.offsets[1:]);trust=self.spec['trust_rad'];stop_selected=set()
        for iteration in range(self.spec['max_iterations']):
            self.check_time(self.spec['audit_reserve_seconds'])
            if current['meta']['passed']:return dict(passed=True,iterations=records),current['arrays']
            selected.update(v['tick'] for v in current['bad']);stop_selected.update(current['worst']);selected.update(t for t,s in stop_selected)
            linear=self.linearize_hierarchy(x,selected,stop_selected);record=dict(iteration=iteration,trust=trust,accepted=False,solvers=[],trials=[])
            step=None
            for level in ['contact','task']:
                self.check_time(self.spec['audit_reserve_seconds']);caps=None if level=='contact' else first[self.map.size:self.map.size+60]
                cost,A,low,high=self.problem(x,linear,trust,caps);self.check_time(self.spec['audit_reserve_seconds']);seconds=min(self.spec['lp_seconds'],self.deadline-time.monotonic()-self.spec['audit_reserve_seconds'])
                primal,dual,info=solve_lp(cost,A,low,high,seconds);record['solvers'].append(dict(level=level,**info));callback.problem(iteration,level,A,low,high,cost,primal,dual,info)
                if not info['passed']:break
                if level=='contact':first=primal
                else:step=primal[:self.map.size]
            if step is None:
                record['status']='numerical_subproblem_not_admitted';records.append(record);callback(iteration,record,None);return dict(passed=False,reason='numerical_subproblem_not_admitted',iterations=records),current['arrays']
            for scale in self.spec['step_scales']:
                self.check_time(self.spec['audit_reserve_seconds']);delta=step*scale;proposal=x+delta;hard=self.map.residual(proposal);prediction=self.predict_vector(current,linear,delta);predicted=float(current['vector']@current['vector']-prediction@prediction)
                if predicted<=0:
                    record['trials'].append(dict(scale=scale,accepted=False,reason='linear_model_no_improvement',predicted_reduction=predicted));continue
                candidate=self.evaluate(proposal);decision=accept_geometry_step(current['vector'],candidate['vector'],hard,predicted,self.spec['min_ratio']);record['trials'].append(dict(scale=scale,geometry=candidate['meta'],decision=decision,predicted_reduction=predicted));callback.trial(iteration,scale,candidate['meta'],candidate['arrays'],decision)
                if decision['accepted']:
                    x=proposal;current=candidate;record['accepted']=True;record['scale']=scale;break
            if record['accepted']:trust=min(self.spec['trust_rad'],trust*1.5)
            else:trust*=.5
            record['incumbent_merit']=current['meta']['merit'];records.append(record);callback(iteration,record,None)
            if current['meta']['passed']:return dict(passed=True,reason='all_original_gates_passed',iterations=records),current['arrays']
            if trust<self.spec['min_trust_rad']:break
        return dict(passed=bool(current['meta']['passed']),reason='all_original_gates_passed' if current['meta']['passed'] else 'bounded_hierarchical_search_without_qualified_path',iterations=records),current['arrays']
