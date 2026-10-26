"""Object-relative arm targets evaluated in the measured floating-base frame.

All kinematic writes are isolated queries. This planner never changes live state
and does not assert force quality or successful physical grasp.
"""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def object_rotation(q):
    return Rotation.from_quat(np.r_[q[54:57],q[53]]).as_matrix()


def relative_targets(arms, template, measured_object):
    delta=object_rotation(measured_object)@object_rotation(template).T
    return {s:(measured_object[50:53]+delta@(p-template[50:53]),delta@r)
            for s,(p,r) in arms.poses(template).items()}


def solve_measured_arms(arms, actual, targets, check_deadline=lambda:None):
    """Bounded least-squares avoids clipped pseudoinverse cycling at joint limits."""
    result=actual.copy();errors={}
    for side,ids in arms.ids.items():
        low,high=arms.ranges[side][:,0]+.005,arms.ranges[side][:,1]-.005
        x0=np.clip(actual[arms.qmap[ids]],low+1e-8,high-1e-8)
        tp,tr=targets[side]
        def residual(x):
            check_deadline();q=result.copy();q[arms.qmap[ids]]=x
            p,r=arms.poses(q)[side]
            return np.r_[(p-tp)/.003,Rotation.from_matrix(r@tr.T).as_rotvec()/.04,(x-x0)*.001]
        solution=least_squares(residual,x0,bounds=(low,high),max_nfev=60,ftol=1e-8,xtol=1e-8,gtol=1e-8)
        result[arms.qmap[ids]]=solution.x
        p,r=arms.poses(result)[side]
        errors[side]=dict(position=float(np.linalg.norm(p-tp)),rotation=float(np.linalg.norm(Rotation.from_matrix(r@tr.T).as_rotvec())),evaluations=solution.nfev)
    return result,errors


def solve_measured_upper(arms, actual, targets, check_deadline=lambda:None):
    """Use the waist and both arms together while retaining measured feet/root."""
    m=arms.m;ids=np.asarray([12,13,14,*arms.ids['left'],*arms.ids['right']])
    joints=[int(np.flatnonzero(m.jnt_qposadr==adr)[0]) for adr in arms.qmap[ids]]
    low,high=m.jnt_range[joints,0]+.005,m.jnt_range[joints,1]-.005
    x0=np.clip(actual[arms.qmap[ids]],low+1e-8,high-1e-8)
    def unpack(x):
        q=actual.copy();q[arms.qmap[ids]]=x;return q
    def residual(x):
        check_deadline();poses=arms.poses(unpack(x));rows=[]
        for side,(tp,tr) in targets.items():
            p,r=poses[side];rows.extend((p-tp)/.003);rows.extend(Rotation.from_matrix(r@tr.T).as_rotvec()/.04)
        return np.r_[rows,(x-x0)*.03]
    solution=least_squares(residual,x0,bounds=(low,high),max_nfev=60,ftol=1e-7,xtol=1e-7,gtol=1e-7)
    result=unpack(solution.x);poses=arms.poses(result)
    errors={s:dict(position=float(np.linalg.norm(poses[s][0]-p)),rotation=float(np.linalg.norm(Rotation.from_matrix(poses[s][1]@r.T).as_rotvec())),evaluations=solution.nfev) for s,(p,r) in targets.items()}
    return result,errors
