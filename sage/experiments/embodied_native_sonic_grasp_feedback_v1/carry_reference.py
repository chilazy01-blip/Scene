"""Yaw-following three-point carrying references with fixed world heights."""
import numpy as np
from scipy.spatial.transform import Rotation

def yaw(quat):
    q=np.asarray(quat);R=Rotation.from_quat(q[[1,2,3,0]]).as_matrix();return float(np.arctan2(R[1,0],R[0,0]))

def capture(root,quat,poses):
    root=np.asarray(root,dtype=float);psi=yaw(quat);R=Rotation.from_euler('z',psi).as_matrix()
    return dict(yaw=psi,root=root.copy(),poses=[(R.T@(np.asarray(p)-root),R.T@np.asarray(r),float(p[2])) for p,r in poses])

def targets(anchor,root,quat):
    root=np.asarray(root,dtype=float);R=Rotation.from_euler('z',yaw(quat)).as_matrix();out=[]
    for p,r,z in anchor['poses']:
        v=root+R@p;v[2]=z;out.append((v,R@r))
    if not np.isfinite(np.concatenate([np.r_[p,r.ravel()] for p,r in out])).all():raise ValueError('nonfinite carrying reference')
    return out
