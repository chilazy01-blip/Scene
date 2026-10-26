"""Inject observed-state reference bounds into the existing collision QP.

Only private kinematics are evaluated. The local displacement prediction remains
an explicit hypothesis; this module does not certify future physical tracking.
"""
import numpy as np
from mink.limits import Constraint
from sage.experiments.embodied_collision_expert_v2.planner_interior import ArmPlanner, collision_roles
from .governor import Proposal, ReferenceRejected


class CombinedLimit:
    def __init__(self, collision_limit, model_nv, arm_dof, lower_delta, upper_delta):
        self.collision_limit = collision_limit
        self.selector = np.eye(model_nv)[arm_dof]
        self.lower_delta, self.upper_delta = lower_delta, upper_delta

    def compute_qp_inequalities(self, configuration, dt):
        collision = self.collision_limit.compute_qp_inequalities(configuration, dt)
        rows = [self.selector, -self.selector]
        rhs = [self.upper_delta, -self.lower_delta]
        if collision.G is not None:
            rows.append(collision.G)
            rhs.append(collision.h)
        return Constraint(G=np.vstack(rows), h=np.concatenate(rhs))


class ReferenceBoundedArmPlanner:
    def __init__(self, context, governor):
        self.c, self.governor = context, governor
        self.planner = ArmPlanner(context)
        self.collision_limit = self.planner.self_limit

    def snapshot(self):
        return dict(version=1, governor=self.governor.snapshot(), solves=self.planner.solves)

    def restore(self, state):
        if (set(state) != {'version', 'governor', 'solves'} or state['version'] != 1
                or type(state['solves']) is not int or state['solves'] < 0):
            raise ReferenceRejected('task_planner_checkpoint')
        self.governor.restore(state['governor'])
        self.planner.solves = state['solves']

    def step(self, tick, measured_qpos, measured_dq, centers, rotations, hand_goal, grasp=False):
        g, c = self.governor, self.c
        q = np.asarray(measured_qpos)[c.qpos]
        dq = np.asarray(measured_dq)
        hand_target = g.reference.copy()
        hand_target[c.hand] = np.asarray(hand_goal)[c.hand]
        hand_proposal = g.preview(tick, q, dq, hand_target)
        dt = g.DT
        velocity_lo = np.maximum(-g.speed_limit, g.velocity - g.acceleration_limit * dt)
        velocity_hi = np.minimum(g.speed_limit, g.velocity + g.acceleration_limit * dt)
        lower = np.maximum.reduce([g.lower, g.reference + velocity_lo * dt,
                                   q - g.error_upper, q + dq * dt - g.error_upper])
        upper = np.minimum.reduce([g.upper, g.reference + velocity_hi * dt,
                                   q - g.error_lower, q + dq * dt - g.error_lower])
        arm = self.planner.arm
        if np.any(lower[arm] > upper[arm] + 1e-12):
            raise ReferenceRejected('task_reference_interval_empty')
        self.planner.self_limit = CombinedLimit(self.collision_limit, c.m.nv,
            self.planner.dadr, lower[arm] - g.reference[arm], upper[arm] - g.reference[arm])
        reference, meta = self.planner.step(measured_qpos, g.reference, centers, rotations,
                                          np.asarray(hand_proposal.reference), grasp)
        if np.any(reference[g.active] < lower[g.active] - 1e-9) or np.any(reference[g.active] > upper[g.active] + 1e-9):
            raise ReferenceRejected('qp_reference_bounds')
        bad, _ = collision_roles(c, self.planner.config.data, grasp)
        if bad:
            raise ReferenceRejected('qp_predicted_geometry')
        velocity = (reference - g.reference) / dt
        meta = dict(meta, max_reference_speed=float(np.max(np.abs(velocity))),
                    max_reference_acceleration=float(np.max(np.abs(velocity - g.velocity) / dt)),
                    constraints_inside_qp=True, future_tracking_certified=False)
        proposal = Proposal(g._hash(g.snapshot()), tick, tuple(reference), tuple(velocity), meta)
        return g.commit(proposal)
