"""Exact native command representation, followed by complete rate/contact revalidation."""
import numpy as np
from .compiler_projected import Compiler as Base
from sage.experiments.embodied_collision_expert_v2.planner_interior import collision_roles

def emit(c,arrays,initial_velocity,grasp,lower,upper,tolerance=2e-8):
    a={k:np.array(v,copy=True) for k,v in arrays.items()};active=a['active'];res=a['residual'];raw=a['reference'];old_initial=a['initial']
    ref=np.clip(raw,lower,upper);initial=np.clip(old_initial,lower,upper);change=max(float(abs(ref-raw).max()),float(abs(initial-old_initial).max()))
    if change>tolerance:raise ValueError('native_representation_change_exceeds_prior_numerical_gate')
    velocity=np.diff(np.vstack([initial,ref]),axis=0)/.02;acceleration=np.diff(np.vstack([initial_velocity,velocity]),axis=0)/.02
    a.update(raw_reference=raw,raw_initial=old_initial,raw_velocity=a['velocity'],raw_acceleration=a['acceleration'],reference=ref,initial=initial,initial_velocity=initial_velocity,velocity=velocity,acceleration=acceleration)
    a['qpos'][:,c.qpos[active]]=ref+res;errors=[];bad=[];stops=[];stop_count=0;stop_native=0.
    for k,q in enumerate(a['qpos']):
        c.d.qpos[:]=q;violations,_=collision_roles(c,c.d,grasp)
        if violations:bad.append(dict(tick=k,bad=violations))
        errors.append([np.linalg.norm(c.d.geom_xpos[c.m.geom('gripper0_'+s+'_g0_col').id]-a['goals'][k,i]) for i,s in enumerate(['left','right'])])
        v=velocity[k].copy();future=ref[k].copy()
        for ss in range(int(np.ceil(abs(v).max()/.5/.02))):
            v=np.sign(v)*np.maximum(abs(v)-.01,0);future+=.02*v;fq=q.copy();fq[c.qpos[active]]=future+res;c.d.qpos[:]=fq;violations,_=collision_roles(c,c.d,grasp);stop_count+=1
            stop_native=max(stop_native,float(np.max(lower-future)),float(np.max(future-upper)))
            if violations:stops.append(dict(tick=k,step=ss+1,bad=violations))
    a['errors']=np.array(errors);hand=c.hand[active];palm=float(a['errors'][-25:].max());he=float(abs(ref[-25:,hand]+res[hand]-a['hand_goals'][-25:,hand]).max());speed=float(abs(velocity).max());acc=float(abs(acceleration).max());endv=float(abs(velocity[-25:]).max())
    native=bool(np.all(ref>=lower) and np.all(ref<=upper));passed=native and not bad and not stops and stop_native<=2e-8 and speed<=.35+2e-7 and acc<=.5+2e-6 and palm<=.006 and he<=.012 and endv<=.08+2e-7
    meta=dict(passed=bool(passed),states=len(ref),exact_reference_native_range=native,max_representation_change_rad=change,max_speed=speed,max_acceleration=acc,endpoint_speed=endv,endpoint_palm_error=palm,endpoint_hand_error=he,current_bad=len(bad),stop_bad=len(stops),stop_states=stop_count,stop_native_excess=stop_native,current_examples=bad[:5],stop_examples=stops[:5])
    return meta,a,bad,stops

class Compiler(Base):
    def solve(self,source,initial,initial_velocity,n,grasp,callback,deadline):
        clipped=np.clip(initial,self.lower,self.upper)
        if np.max(abs(clipped-initial))>2e-8:raise ValueError('invalid_entering_reference')
        self.entering_velocity=initial_velocity.copy()
        return super().solve(source,clipped,initial_velocity,n,grasp,callback,deadline)
    def audit(self,coeff,mat,source,initial,grasp):
        raw,a,bad,stops=super().audit(coeff,mat,source,initial,grasp)
        meta,a,bad,stops=emit(self.c,a,self.entering_velocity,grasp,self.lower,self.upper)
        meta['phase_excess']=raw['phase_excess'];meta['passed']=meta['passed'] and raw['phase_excess']<=2e-8
        meta['unrounded_geometry']=raw
        return meta,a,bad,stops
