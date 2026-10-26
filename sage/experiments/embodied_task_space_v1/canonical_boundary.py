"""Canonicalize only floating-point noise at an already accepted native boundary."""
import numpy as np
from .compiler_projected import Compiler as Base

def canonicalize(reference,lower,upper,tolerance=1e-12):
    reference=np.asarray(reference);clipped=np.clip(reference,lower,upper)
    error=float(np.max(abs(clipped-reference),initial=0.))
    if error>tolerance:raise ValueError('boundary_change_exceeds_roundoff_allowance')
    return clipped,dict(max_change_rad=error,changed_joints=int(np.count_nonzero(clipped!=reference)),tolerance_rad=tolerance)

class Compiler(Base):
    def solve(self,source,initial,initial_velocity,n,grasp,callback,deadline):
        initial,info=canonicalize(initial,self.lower,self.upper)
        result,arrays=super().solve(source,initial,initial_velocity,n,grasp,callback,deadline)
        result['boundary_canonicalization']=info
        return result,arrays
