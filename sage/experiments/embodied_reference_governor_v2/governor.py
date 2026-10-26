"""Add conservative native-limit braking viability to v1 reference transactions.

For each next signed speed v, reserve v*dt + v**2/(2*a) before the
native boundary. This is sufficient for sampled maximum deceleration; it
is a reference-generator invariant, not a bound on the physical robot.
"""
import numpy as np
from sage.experiments.embodied_reference_governor_v1.governor import ReferenceGovernor as Base, ReferenceRejected, Proposal, vector

class ReferenceGovernor(Base):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.feedback_rate=np.minimum(4.,self.acceleration_limit/self.speed_limit)
        self.config_sha256=self._hash(dict(base=self.config_sha256,law='native_continuous_braking_reserve_v2',feedback_rate=self.feedback_rate.tolist()))

    def admissible_bounds(self,q,dq):
        q,dq=vector(q,'q'),vector(dq,'dq');dt=self.DT
        error=q-self.reference
        if np.any(self.active & ((error<self.error_lower-1e-9)|(error>self.error_upper+1e-9))):
            raise ReferenceRejected('observed_tracking_budget')
        a=self.acceleration_limit
        positive=-a*dt+np.sqrt((a*dt)**2+2*a*np.maximum(0.,self.upper-self.reference))
        negative=-a*dt+np.sqrt((a*dt)**2+2*a*np.maximum(0.,self.reference-self.lower))
        vlo=np.maximum.reduce([-self.speed_limit,self.velocity-a*dt,-negative])
        vhi=np.minimum.reduce([self.speed_limit,self.velocity+a*dt,positive])
        lower=np.maximum.reduce([self.lower,self.reference+vlo*dt,q-self.error_upper,q+dq*dt-self.error_upper])
        upper=np.minimum.reduce([self.upper,self.reference+vhi*dt,q-self.error_lower,q+dq*dt-self.error_lower])
        lower[~self.active]=upper[~self.active]=self.reference[~self.active]
        if np.any(lower>upper+1e-12):raise ReferenceRejected('braking_admissible_interval_empty')
        return lower,upper

    def preview(self,tick,observed_q,observed_dq,target):
        if type(tick) is not int or tick!=self.next_tick:raise ReferenceRejected('nonsequential_tick')
        q,dq,target=[vector(v,n) for v,n in [(observed_q,'q'),(observed_dq,'dq'),(target,'target')]]
        if np.any(target<self.lower) or np.any(target>self.upper):raise ReferenceRejected('target_native_range')
        if np.any(abs(target[~self.active]-self.reference[~self.active])>1e-12):raise ReferenceRejected('inactive_target_changed')
        lo,hi=self.admissible_bounds(q,dq);desired=np.clip(self.feedback_rate*(target-self.reference),-self.speed_limit,self.speed_limit)
        ref=np.clip(self.reference+desired*self.DT,lo,hi);velocity=(ref-self.reference)/self.DT
        meta=dict(max_delta_rad=float(abs(ref-self.reference).max()),max_reference_speed=float(abs(velocity).max()),max_reference_acceleration=float((abs(velocity-self.velocity)/self.DT).max()),evidence_id=self.evidence_id,native_braking_reserve=True,future_tracking_certified=False)
        return Proposal(self._hash(self.snapshot()),tick,tuple(ref),tuple(velocity),meta)

    def commit(self,proposal):
        if not isinstance(proposal,Proposal):raise ReferenceRejected('proposal_type')
        velocity=vector(proposal.velocity,'proposal_velocity');distance=np.where(velocity>=0,self.upper-self.reference,self.reference-self.lower)
        reserve=abs(velocity)*self.DT+velocity**2/(2*self.acceleration_limit)
        if np.any(self.active & (reserve>distance+1e-10)):raise ReferenceRejected('native_braking_viability')
        return super().commit(proposal)
