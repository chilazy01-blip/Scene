"""Observed expert; writes private planning geometry and native commands only."""
import copy
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_phase_coordinator_v1.coordinator import (
    Coordinator, Observation, Goal, CoordinationRejected)
from sage.experiments.embodied_phase_coordinator_v1.native_packet import packet
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner, collision_roles


class PaceCoordinator(Coordinator):
    """Mid-phase tracking holds consume the same six-second phase allowance."""
    def step(self, observation, goal, *, advance_allowed=True):
        previous = self.local_tick
        result = super().step(observation, goal)
        if not advance_allowed and not result['phase_advanced'] and self.local_tick > previous:
            self.local_tick = previous
            self.extra_ticks += 1
            if self.extra_ticks > self.MAX_EXTRA_TICKS:
                self.extra_ticks = self.MAX_EXTRA_TICKS
                self.failure = 'phase_tracking_timeout'
                raise CoordinationRejected(self.failure)
        result['tracking_hold'] = not advance_allowed
        return result

    def restore(self, state):
        if type(state.get('done')) is not bool or state.get('failure') not in (
                None,'unsafe_or_out_of_domain','total_duration','phase_recovery_timeout','phase_tracking_timeout'):
            raise CoordinationRejected('checkpoint_terminal_type')
        super().restore(copy.deepcopy(state))


class Expert:
    def __init__(self, context, stages, intent, envelope):
        self.c,self.stages,self.intent = context,stages,intent
        self.clock = PaceCoordinator(stages)
        self.planner = ArmPlanner(context)
        self.reference = context.nominal.copy()
        self.centers0 = [context.d.geom_xpos[context.m.geom('gripper0_'+s+'_g0_col').id].copy()
                         for s in ['left','right']]
        self.rotations0 = [context.d.xmat[context.m.body('gripper0_'+s+'_'+s+'_hand_palm_link').id].reshape(3,3).copy()
                           for s in ['left','right']]
        self.envelope = envelope

    def snapshot(self):
        return dict(clock=self.clock.snapshot(),reference=self.reference.tolist(),
                    centers0=[x.tolist() for x in self.centers0],
                    rotations0=[x.tolist() for x in self.rotations0])

    def restore(self, state):
        self.c.validate(state['reference'])
        self.clock.restore(state['clock'])
        self.reference = np.array(state['reference'])
        self.centers0 = [np.array(x) for x in state['centers0']]
        self.rotations0 = [np.array(x) for x in state['rotations0']]
        if np.shape(self.centers0)!=(2,3) or np.shape(self.rotations0)!=(2,3,3):
            raise CoordinationRejected('checkpoint_targets')
        if not np.isfinite(self.centers0).all() or not np.isfinite(self.rotations0).all():
            raise CoordinationRejected('checkpoint_targets_finite')

    def step(self, tick, task_ready, geometry_safe):
        c=self.c
        logical=self.stages[self.clock.stage_index][1]+self.clock.local_tick*.02
        v=self.intent(c,logical,self.centers0,self.rotations0)
        # Nominal task goals remain world-frame desired object poses. Actual
        # object pose/force enters task guards and collision constraints; it is
        # never assigned to the physical model to satisfy the goal.
        actual=[c.d.geom_xpos[c.m.geom('gripper0_'+s+'_g0_col').id] for s in ['left','right']]
        error=max(float(np.linalg.norm(a-b)) for a,b in zip(actual,v['centers']))
        yaw=Rotation.from_quat(c.d.qpos[[4,5,6,3]]).as_euler('xyz')[2]
        delta=c.d.qpos[:2]-[v['planned_x'],v['planned_y']]
        yaw_error=abs(np.arctan2(np.sin(yaw-v['heading']),np.cos(yaw-v['heading'])))
        residual=c.d.qpos[c.qpos]-self.reference
        mask=~np.isin(np.arange(43),c.lower_indices)
        lo=np.minimum(0.,self.envelope['joint_error_min'])
        hi=np.maximum(0.,self.envelope['joint_error_max'])
        domain=(abs(delta[0])<=.04+1e-9 and abs(delta[1])<=.08+1e-9
                and yaw_error<=.04+self.envelope['rpy_abs_max'][2]+1e-9
                and abs(c.d.qpos[2]-v['height'])<=.05
                and np.all(residual[mask]>=lo[mask]-1e-9)
                and np.all(residual[mask]<=hi[mask]+1e-9))
        ref,meta=self.planner.step(c.d.qpos,self.reference,v['centers'],v['rotations'],v['hand'],v['grasp'])
        bad,_=collision_roles(c,self.planner.config.data,v['grasp'])
        if bad:raise CoordinationRejected('predicted_forbidden_geometry')
        observation=Observation(tick,tuple(c.d.qpos[:2]),float(yaw),float(c.d.qpos[2]),
                                float(np.linalg.norm(c.d.qvel[:3])),error,
                                bool(task_ready),bool(geometry_safe),bool(domain))
        goal=Goal((v['planned_x'],v['planned_y']),v['heading'],v['height'],v['height'])
        pacing=abs(delta[0])<=.03 and abs(delta[1])<=.06 and error<=.012
        command=self.clock.step(observation,goal,advance_allowed=pacing)
        self.reference=ref
        return packet(command,ref),dict(command=command,logical_time=logical,
                    measured_palm_error=error,predicted=meta,grasp=v['grasp'],
                    desired_object_pose=v['object_pose'].tolist(),domain=bool(domain))
