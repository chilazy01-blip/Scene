"""Bounded Cartesian reference correction; this never produces motor commands."""
import numpy as np


def limited(vector,maximum):
    x=np.asarray(vector,dtype=float)
    return x*min(1.,maximum/max(float(np.linalg.norm(x)),1e-15))


class ReferenceFeedback:
    def __init__(self):
        self.position=np.zeros(3);self.rotation=np.zeros(3)

    def update(self,position_error,rotation_error,dt):
        if not 0<=dt<=.100001 or not np.isfinite([*position_error,*rotation_error]).all():
            raise ValueError('invalid reference feedback observation')
        self.position=limited(self.position+limited(2.*dt*np.asarray(position_error),.01),.06)
        self.rotation=limited(self.rotation+limited(2.*dt*np.asarray(rotation_error),.04),.30)
        return self.position.copy(),self.rotation.copy()
