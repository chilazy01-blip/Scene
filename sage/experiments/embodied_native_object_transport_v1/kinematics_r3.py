"""Bounded rescue seed for an outward positive-elbow IK local minimum."""

import numpy as np
from .kinematics_r2 import IK as BaseIK, ARM_NAMES


class IK(BaseIK):
    def solve(self,qpos,position,rotation,max_evaluations=80):
        a=super().solve(qpos,position,rotation,max_evaluations)
        if a['position_error_m']<.002 and a['orientation_error_rad']<.02:return a
        seed=np.asarray(qpos).copy()
        seed[self.qids]=[.16854,-.56712,-.55405,.77506,.66015,-.49901,.95891]
        b=super().solve(seed,position,rotation,max_evaluations)
        return min((a,b),key=lambda r:10*r['position_error_m']+r['orientation_error_rad'])
