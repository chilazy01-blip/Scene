"""Original contact linearization with all 25 terminal task samples retained."""
import numpy as np
import mujoco
from scipy import sparse
from sage.experiments.embodied_geometry_feasibility_v1.discrete_stop import trajectory
from sage.experiments.embodied_task_space_v2.joint_compiler import GRASP

def linearize_terminal_window(self,x,selected,stop_selected):
    m=self.map;ref,progress,vel,acc=m.values(x);geo=[];bounds=[];true_bounds=[];groups=[];labels=[];descriptors=[];endpoints=[];tracking=[];protected=[];steps={}
    for tick,step in stop_selected:steps.setdefault(tick,set()).add(step)
    for tick in sorted(selected):
        self.check_time(5.);phase=int(self.phase_of[tick]);s=self.sources[phase];p=float(np.clip(progress[tick],0,1));q,goal,hand=s.at(p);q[self.qadr]=ref[tick]+self.residual;self.planner.config.update(q)
        dv,dgoal,dhand=s.derivative(p,ref[tick]);jac=[];err=[]
        for k,side in enumerate(['left','right']):
            gid=self.c.m.geom('gripper0_'+side+'_g0_col').id;jp=np.zeros((3,self.c.m.nv));mujoco.mj_jacGeom(self.c.m,self.planner.config.data,jp,None,gid)
            jac.append(np.c_[jp[:,self.dadr],jp@dv-dgoal[k]]);err.extend(self.planner.config.data.geom_xpos[gid]-goal[k])
        task=m.embed(np.vstack(jac),tick);error=np.array(err);ht=m.embed(np.c_[np.eye(self.j)[self.hand],-dhand[self.hand]],tick);he=ref[tick,self.hand]+self.residual[self.hand]-hand[self.hand]
        if tick>=m.offsets[phase+1]-25:endpoints.append((phase,task,error,ht,he))
        if self.current['meta']['phases'][phase]['passed'] and tick>=m.offsets[phase+1]-25:protected.append((phase,tick,task,error,ht,he))
        if tick%self.spec['search_stride']==0:tracking.append((phase,task,error))
        future=trajectory(ref[tick],vel[tick]) if tick in steps else []
        grasp=self.stages[phase][0] in GRASP
        for stop in [0]+sorted(steps.get(tick,[])):
            forecast=q.copy()
            if stop:forecast[self.qadr]=(future[min(stop,len(future))-1] if future else ref[tick])+self.residual
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
    assert len(endpoints)==15*25
    return dict(G=sparse.vstack(geo,format='csr'),h=np.array(bounds),true_h=np.array(true_bounds),groups=np.array(groups),labels=np.array(labels),descriptors=np.array(descriptors),endpoints=endpoints,tracking=tracking,protected=protected)
