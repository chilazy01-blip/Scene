"""Original finger position PD, with bounded contact-informed closure references."""
import numpy as np


def preload(closure,forces,dt,maximum=.50,rate=.10):
    if not np.isfinite(closure) or not np.isfinite(dt) or dt<0:raise ValueError('invalid closure state')
    support=min(float(forces['thumb']),float(forces['index'])+float(forces['middle']))
    if support<2.0:closure+=rate*dt
    return float(np.clip(closure,0,maximum))


def secure(forces):
    return forces['thumb']>=1.0 and forces['index']>=.10 and forces['index']+forces['middle']>=1.0
