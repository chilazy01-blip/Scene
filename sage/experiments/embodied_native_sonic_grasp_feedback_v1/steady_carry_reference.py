"""Carry the grasp pose by base XY translation without base yaw jitter."""
import numpy as np
from scipy.spatial.transform import Rotation
from .carry_reference import targets as following_targets

def targets(anchor,root,quat):
    out=following_targets(anchor,root,quat);A=Rotation.from_euler('z',anchor['yaw']).as_matrix();p,R,z=anchor['poses'][0];world=anchor['root']+A@p;world[:2]+=np.asarray(root)[:2]-anchor['root'][:2];world[2]=z;out[0]=(world,A@R);return out
