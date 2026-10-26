"""Bounded command-bias adaptation; never changes native actuator gains/laws."""
from dataclasses import dataclass
import math
from ..repair_v2.progress import ControlRejected


@dataclass(frozen=True)
class FeedbackLimits:
    dt: float = .02
    integral_gain: float = 1.
    error_deadband: float = .002
    bias_limit: float = .15
    bias_rate: float = .1
    velocity: float = 1.
    acceleration: float = 4.


class BoundedBias:
    """Slow error integration plus limits on the actual issued target.

    The nominal target can contain a justified initial grip preload. The adaptive
    term is separate and starts at zero at each measured path handoff. Clipping
    freezes integration; bounds prevent accumulating hidden correction. A failed
    safety check commits neither the correction nor the issued command.
    """
    def __init__(self, initial_command, limits=FeedbackLimits()):
        if any(not math.isfinite(v) or v <= 0 for v in vars(limits).values()):
            raise ValueError('invalid_feedback_limits')
        self.limits=limits
        self.last=list(map(float,initial_command))
        if not self.last or not all(map(math.isfinite,self.last)):
            raise ValueError('invalid_feedback_initial_command')
        self.integration_enabled=[True]*len(self.last)
        self.bias=[0.]*len(self.last)
        self.velocity=[0.]*len(self.last)

    def step(self, nominal, expected, actual, *, saturated=False, bounds=None, safe=lambda command:True):
        values=[list(map(float,x)) for x in (nominal,expected,actual)]
        if any(len(v)!=len(self.last) or not all(map(math.isfinite,v)) for v in values):
            raise ControlRejected('invalid_feedback_observation')
        nominal,expected,actual=values;l=self.limits
        bounds=[(-math.inf,math.inf)]*len(self.last) if bounds is None else list(bounds)
        if len(bounds)!=len(self.last) or any(math.isnan(lo) or math.isnan(hi) or lo>=hi for lo,hi in bounds):
            raise ValueError('invalid_command_bounds')
        bias=[];target=[];issued=[];velocity=[]
        clipped=[]
        for index,(n,e,q,b,last,v,(lo,hi)) in enumerate(zip(nominal,expected,actual,self.bias,self.last,self.velocity,bounds)):
            error=e-q
            correction=0. if saturated or not self.integration_enabled[index] or abs(error)<=l.error_deadband else l.integral_gain*error*l.dt
            correction=max(-l.bias_rate*l.dt,min(l.bias_rate*l.dt,correction))
            next_bias=max(-l.bias_limit,min(l.bias_limit,b+correction))
            # At a target bound integrate only towards the feasible interval.
            if (n+next_bias>hi and correction>0) or (n+next_bias<lo and correction<0):
                next_bias=b
            b=next_bias;bias.append(b)
            desired=max(lo,min(hi,n+b));target.append(desired);clipped.append(desired!=n+b)
            distance=desired-last
            # Rest-to-rest envelope also applies to a correction target reversal.
            stopping=max(0.,math.sqrt((l.acceleration*l.dt)**2+2*l.acceleration*abs(distance))-l.acceleration*l.dt)
            want=math.copysign(min(l.velocity,stopping),distance) if distance else 0.
            vn=max(v-l.acceleration*l.dt,min(v+l.acceleration*l.dt,want))
            vn=max(-l.velocity,min(l.velocity,vn))
            direct=distance/l.dt
            if abs(direct)<=l.velocity and abs(direct-v)<=l.acceleration*l.dt and abs(distance)<1e-6:
                vn=direct
            issued.append(last+vn*l.dt);velocity.append(vn)
            if issued[-1]<lo-1e-10 or issued[-1]>hi+1e-10:
                raise ControlRejected('feedback_command_bound')
        if not safe(issued):
            raise ControlRejected('feedback_command_rejected')
        acceleration=max(abs(a-b)/l.dt for a,b in zip(velocity,self.velocity))
        self.bias,self.last,self.velocity=bias,issued,velocity
        return issued.copy(),dict(bias=bias.copy(),requested_target=target,
            peak_velocity=max(map(abs,velocity)),peak_acceleration=acceleration,
            integration_frozen=bool(saturated),integration_enabled=list(self.integration_enabled),target_clipped=clipped,
            bias_at_bound=any(abs(b)>=l.bias_limit-1e-12 for b in bias))
