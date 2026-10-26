"""Time-resample the loaded walking reference without changing motor or physics rates."""
import numpy as np
from scipy.spatial.transform import Rotation,Slerp

def retime(q,v,rate=.65):
    q=np.asarray(q,dtype=float);v=np.asarray(v,dtype=float)
    if q.ndim!=2 or q.shape[1]!=36 or v.shape!=(len(q),29) or len(q)<46 or not np.isfinite(q).all() or not np.isfinite(v).all() or not np.isfinite(rate) or not 0<rate<=1:raise ValueError('invalid walking reference or phase rate')
    if np.max(np.abs(np.linalg.norm(q[:,3:7],axis=1)-1))>1e-3:raise ValueError('unnormalized reference root quaternion')
    time=np.arange(len(q));phase=np.minimum(np.arange(int(np.ceil((len(q)-1)/rate))+1)*rate,len(q)-1)
    out=np.empty((len(phase),36));outv=np.empty((len(phase),29))
    for j in list(range(3))+list(range(7,36)):out[:,j]=np.interp(phase,time,q[:,j])
    rotations=Rotation.from_quat(q[:,[4,5,6,3]])
    out[:,3:7]=Slerp(time,rotations)(phase).as_quat()[:,[3,0,1,2]]
    for j in range(29):outv[:,j]=np.interp(phase,time,v[:,j])*rate
    return out,outv
