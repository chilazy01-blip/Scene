"""Admit a body preview jointly with rate-limited arm/hand references.

The preview is private kinematics. Returning body_advance=False asks the
caller to hold its body target, never to overwrite a physical body pose.
Actual body tracking and stopping delay still require separate qualification.
"""
import copy
import numpy as np
from sage.experiments.embodied_reference_governor_v3.task_planner import ReferenceBoundedArmPlanner
from sage.experiments.embodied_reference_governor_v1.governor import ReferenceRejected

class BodyReferenceAdmission:
    def __init__(self,context,governor):
        self.c=context;self.planner=ReferenceBoundedArmPlanner(context,governor);self.attempts=0
    @property
    def governor(self):return self.planner.governor
    def snapshot(self):return dict(version=1,planner=self.planner.snapshot(),attempts=self.attempts)
    def restore(self,state):
        if set(state)!={'version','planner','attempts'} or state['version']!=1 or type(state['attempts']) is not int or state['attempts']<0:raise ReferenceRejected('body_admission_checkpoint')
        self.planner.restore(copy.deepcopy(state['planner']));self.attempts=state['attempts']
    def step(self,tick,measured_qpos,measured_dq,body_preview,centers,rotations,hand_goal,grasp=False):
        measured=np.asarray(measured_qpos);preview=np.asarray(body_preview)
        if measured.shape!=(self.c.m.nq,) or preview.shape!=measured.shape or not np.isfinite(measured).all() or not np.isfinite(preview).all():raise ReferenceRejected('body_preview_shape_finite')
        active=self.c.qpos[self.governor.active]
        if np.max(abs(preview[active]-measured[active]))>1e-12:raise ReferenceRejected('body_preview_changes_observed_upper_joints')
        before=self.planner.snapshot();failures=[]
        for advance,q in [(True,preview),(False,measured)]:
            self.attempts+=1
            try:
                ref,meta=self.planner.step(tick,q,measured_dq,centers,rotations,hand_goal,grasp)
                return ref,dict(body_advance=advance,predicted=meta,rejected_previews=failures,qp_attempts=self.attempts,body_future_tracking_certified=False)
            except (ValueError,RuntimeError) as exc:
                failures.append(dict(body_advance=advance,reason=str(exc)));self.planner.restore(before)
        raise ReferenceRejected('body_and_arm_admission_infeasible:'+repr(failures))
