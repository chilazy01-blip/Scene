"""Coordinated, bounded command curves; no independent joint clipping.

All joints share a segment parameter. Rest-to-rest segments follow a straight
joint-space path. Moving splices preserve position, velocity and acceleration;
their curved geometry must be validated before committing them. Bernstein hull
bounds certify joint ranges and continuous velocity/acceleration bounds.
"""
from dataclasses import dataclass
from math import comb
import numpy as np


def bernstein_bounds(coefficients):
    c=np.asarray(coefficients,dtype=float);n=len(c)-1
    b=np.asarray([sum((c[i]*comb(k,i)/comb(n,i) for i in range(k+1)),
                     np.zeros(c.shape[1])) for k in range(n+1)])
    return b.min(axis=0),b.max(axis=0)


@dataclass(frozen=True)
class Segment:
    coefficients: np.ndarray
    duration: float

    @classmethod
    def connect(cls,q,v,a,target,duration):
        q,v,a,target=map(lambda x:np.asarray(x,dtype=float),(q,v,a,target))
        if not all(x.shape==q.shape and np.isfinite(x).all() for x in (v,a,target)) or not np.isfinite(duration) or duration<=0:
            raise ValueError('invalid_coordinated_segment')
        c=np.zeros((6,len(q)));c[0]=q;c[1]=duration*v;c[2]=.5*duration**2*a
        delta=target-q;c[3]=10*delta-6*c[1]-3*c[2];c[4]=-15*delta+8*c[1]+3*c[2];c[5]=6*delta-3*c[1]-c[2]
        return cls(c,float(duration))

    def sample(self,time):
        s=float(np.clip(time/self.duration,0.,1.));c=self.coefficients
        q=np.polynomial.polynomial.polyval(s,c)
        v=np.polynomial.polynomial.polyval(s,c[1:]*np.arange(1,6)[:,None])/self.duration
        a=np.polynomial.polynomial.polyval(s,c[2:]*(np.arange(2,6)*np.arange(1,5))[:,None])/self.duration**2
        return q,v,a

    def bounds(self):
        c=self.coefficients
        return (bernstein_bounds(c),bernstein_bounds(c[1:]*np.arange(1,6)[:,None]/self.duration),
                bernstein_bounds(c[2:]*(np.arange(2,6)*np.arange(1,5))[:,None]/self.duration**2))


class Route:
    def __init__(self,segments,kind='target'):
        self.segments=tuple(segments);self.duration=sum(x.duration for x in segments);self.kind=kind
        if not segments:raise ValueError('empty_route')

    def sample(self,time):
        t=max(0.,float(time))
        for segment in self.segments:
            if t<=segment.duration:return segment.sample(t)
            t-=segment.duration
        return self.segments[-1].sample(self.segments[-1].duration)

    def validation_times(self,start=0.,dt=.02,angular_step=.01,max_samples=513):
        # Time samples include every command tick and small angular increments.
        values=[float(start),self.duration];offset=0.
        for seg in self.segments:
            lo,hi=seg.bounds()[1];speed=float(np.max(np.maximum(abs(lo),abs(hi))))
            spacing=min(dt,angular_step/max(speed,1e-12))
            begin=max(0.,start-offset)
            if begin<=seg.duration:
                count=int(np.ceil((seg.duration-begin)/spacing))+1
                if count>max_samples:raise ValueError('geometry_sampling_budget_exceeded')
                values.extend(offset+np.linspace(begin,seg.duration,count))
            offset+=seg.duration
        result=np.unique(np.clip(values,start,self.duration))
        if len(result)>max_samples:raise ValueError('geometry_sampling_budget_exceeded')
        return result


class CoordinatedPlanner:
    def __init__(self,lower,upper,vmax,amax,dt=.02,max_duration=2.):
        self.lower,self.upper,self.vmax,self.amax=map(lambda x:np.asarray(x,dtype=float),(lower,upper,vmax,amax))
        self.dt=float(dt);self.max_duration=float(max_duration)
        if not all(x.shape==self.lower.shape and np.isfinite(x).all() for x in (self.upper,self.vmax,self.amax)) or np.any(self.lower>=self.upper) or np.any(self.vmax<=0) or np.any(self.amax<=0):
            raise ValueError('invalid_coordinated_limits')

    def bounded(self,segment):
        (lo,hi),(vl,vh),(al,ah)=segment.bounds()
        return bool(np.all(lo>=self.lower-1e-10) and np.all(hi<=self.upper+1e-10) and
                    np.all(vl>=-self.vmax-1e-9) and np.all(vh<=self.vmax+1e-9) and
                    np.all(al>=-self.amax-1e-8) and np.all(ah<=self.amax+1e-8))

    def connect(self,q,v,a,target):
        q,v,a,target=map(lambda x:np.asarray(x,dtype=float),(q,v,a,target))
        if not all(x.shape==self.lower.shape and np.isfinite(x).all() for x in (q,v,a,target)):
            raise ValueError('invalid_coordinated_state')
        if np.any(target<self.lower) or np.any(target>self.upper):return None
        delta=abs(target-q)
        initial=max(2*self.dt,float(np.max(5*delta/self.vmax)),float(np.max(np.sqrt(20*delta/self.amax))),float(np.max(2*abs(v)/self.amax)))
        # Global duration search, never an individual joint rate/position clamp.
        for scale in [1.,1.2,1.5,2.,3.,4.]:
            duration=np.ceil(initial*scale/self.dt)*self.dt
            if duration>self.max_duration+1e-12:break
            segment=Segment.connect(q,v,a,target,duration)
            if self.bounded(segment):return segment
        return None

    def stop_candidates(self,q,v,a):
        # C2 shared-time stop. Endpoint follows the incoming command history.
        initial=max(2*self.dt,float(np.max(3*abs(v)/self.amax)))
        for scale in [1.,1.5,2.,3.,4.]:
            duration=np.ceil(initial*scale/self.dt)*self.dt
            if duration>self.max_duration:break
            target=q+.5*v*duration+a*duration**2/12
            segment=Segment.connect(q,v,a,target,duration)
            if self.bounded(segment):yield Route([segment],kind='stop')

    def target_candidates(self,q,v,a,target,waypoints=()):
        segment=self.connect(q,v,a,target)
        if segment is not None:
            yield Route([segment])
            # Collision/approach constraints may require slower shared timing.
            # A moving splice is rebuilt and rechecked at each global duration.
            for scale in [1.5,2.,3.,4.]:
                duration=np.ceil(segment.duration*scale/self.dt)*self.dt
                if duration>self.max_duration+1e-12:break
                slower=Segment.connect(q,v,a,target,duration)
                if self.bounded(slower):yield Route([slower])
        for waypoint in waypoints:
            first=self.connect(q,v,a,waypoint)
            second=self.connect(waypoint,np.zeros_like(v),np.zeros_like(a),target)
            if first is not None and second is not None:
                for scale in [1.,1.5,2.]:
                    first_time=np.ceil(first.duration*scale/self.dt)*self.dt
                    second_time=np.ceil(second.duration*scale/self.dt)*self.dt
                    if first_time+second_time>self.max_duration+1e-12:break
                    part1=Segment.connect(q,v,a,waypoint,first_time)
                    part2=Segment.connect(waypoint,np.zeros_like(v),np.zeros_like(a),target,second_time)
                    if self.bounded(part1) and self.bounded(part2):yield Route([part1,part2],kind='waypoint')
