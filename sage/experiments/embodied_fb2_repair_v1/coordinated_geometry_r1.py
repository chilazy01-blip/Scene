"""Two collision branches and bounded kinematic lookahead on query models only.

Agreement is a necessary gate, not a proof of geometric truth or dynamics.
Prediction uses measured velocity of the free body, lower joints and object;
all final upper commands are sampled. Nothing writes to a live simulator.
"""
import numpy as np
import mujoco
from .geometry import ClearanceGuard
from .proximity import TableApproachGuard
from scipy.spatial import ConvexHull


class ProspectiveClearance:
    def __init__(self,model,qmap,indices,gap=.0002,hand_penetration=.005):
        self.current=ClearanceGuard(model,gap,hand_penetration)
        self.alternative=ClearanceGuard(model,gap,hand_penetration)
        self.alternative.model.opt.enableflags|=int(mujoco.mjtEnableBit.mjENBL_NATIVECCD)
        self.table=TableApproachGuard(model)
        # Rigidly transformed mesh extrema occur on its convex hull. Retain the
        # original vertex ordering on the hull for deterministic support points.
        self.table.meshes=[(gid,name,vertices[np.sort(ConvexHull(vertices).vertices)]
                            if len(vertices)>32 else vertices)
                           for gid,name,vertices in self.table.meshes]
        self.mapping=np.asarray(qmap);self.indices=np.asarray(indices)
        self.qids=self.mapping[self.indices];self.dofs=self.qids-1

    def check(self,q):
        a=self.current.check(q);b=self.alternative.check(q)
        return dict(passed=a['passed'] and b['passed'],current=a,alternative=b,
                    classification_disagreement=a['passed']!=b['passed'],
                    scope='two_branch_sampled_geometry_not_physical_certification')

    def bind(self,actual_q,actual_v,deadline=lambda:None):
        q=np.asarray(actual_q,dtype=float).copy();v=np.asarray(actual_v,dtype=float).copy()
        if q.shape!=(self.current.model.nq,) or v.shape!=(self.current.model.nv,) or not np.isfinite(q).all() or not np.isfinite(v).all():
            raise ValueError('finite_actual_full_state_required')

        def validate(route,elapsed=0.,approach=False):
            checks=0
            try:times=route.validation_times(elapsed)
            except ValueError as e:return dict(passed=False,reason=str(e),checks=0)
            for t in times:
                deadline();future=q.copy();velocity=v.copy();velocity[self.dofs]=0
                # This is coordinate extrapolation on a scratch array, not mj_step.
                mujoco.mj_integratePos(self.current.model,future,velocity,float(t-elapsed))
                position,command_velocity,_=route.sample(float(t));future[self.qids]=position
                result=self.check(future);checks+=1
                if not result['passed']:return dict(passed=False,reason='prospective_geometry',time=float(t-elapsed),geometry=result,checks=checks)
                if approach:
                    velocity[self.dofs]=command_velocity
                    safety=self.table.evaluate(future,velocity)
                    if not safety['safe_to_approach']:
                        return dict(passed=False,reason='prospective_table_approach',time=float(t-elapsed),risk_points=[p for p in safety['points'] if p['risk']],checks=checks)
            # Actual tracking-to-command geometry is separate from command history.
            position=route.sample(min(route.duration,elapsed+.02))[0]
            for mix in np.linspace(0.,1.,9):
                deadline();candidate=q.copy();candidate[self.qids]+=(position-q[self.qids])*mix
                result=self.check(candidate);checks+=1
                if not result['passed']:return dict(passed=False,reason='actual_to_next_command_geometry',fraction=float(mix),geometry=result,checks=checks)
            return dict(passed=True,checks=checks,horizon_seconds=route.duration-elapsed,
                        scope='sampled_constant_measured_velocity_forecast_not_dynamic_certificate')
        return validate
