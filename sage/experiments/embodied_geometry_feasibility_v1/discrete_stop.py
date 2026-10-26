"""Independent joint deceleration; distinct from the old uniform-ramp law."""
import numpy as np


def reserve(speed=.35, acceleration=.5, dt=.02):
    delta=speed*dt; decrement=acceleration*dt*dt
    if delta<=decrement:return 0.,0.
    maximum=sum(max(delta-k*decrement,0.) for k in range(1,int(np.ceil(delta/decrement))+1))
    coefficient=maximum/(delta-decrement)
    return coefficient,coefficient*decrement


def trajectory(reference, velocity, acceleration=.5, dt=.02):
    q=np.asarray(reference).copy();v=np.asarray(velocity).copy();result=[]
    for _ in range(int(np.ceil(np.max(abs(v),initial=0)/acceleration/dt))):
        v=np.sign(v)*np.maximum(abs(v)-acceleration*dt,0.)
        q=q+dt*v;result.append(q.copy())
    return result
