"""Transactional reference generator; no simulator state or policy is modified.

The velocity extrapolation is an admission hypothesis, not a dynamics proof.
Experiment-specific error limits must carry a separate evidence identifier.
"""
from dataclasses import dataclass
import copy
import hashlib
import json
import numpy as np


class ReferenceRejected(ValueError):
    pass


def vector(value, name):
    result = np.array(value, dtype=np.float64, copy=True)
    if result.shape != (43,) or not np.isfinite(result).all():
        raise ReferenceRejected(name + '_shape_finite')
    return result


@dataclass(frozen=True)
class Proposal:
    before_sha256: str
    tick: int
    reference: tuple
    velocity: tuple
    diagnostics: dict


class ReferenceGovernor:
    DT = .02

    def __init__(self, initial, lower, upper, active, speed_limit,
                 acceleration_limit, error_lower, error_upper, evidence_id):
        self.reference = vector(initial, 'initial')
        self.lower = vector(lower, 'lower')
        self.upper = vector(upper, 'upper')
        self.active = np.asarray(active, dtype=bool).copy()
        self.speed_limit = vector(speed_limit, 'speed_limit')
        self.acceleration_limit = vector(acceleration_limit, 'acceleration_limit')
        self.error_lower = vector(error_lower, 'error_lower')
        self.error_upper = vector(error_upper, 'error_upper')
        self.evidence_id = str(evidence_id)
        if (self.active.shape != (43,) or np.any(self.lower > self.upper)
                or np.any(self.error_lower > self.error_upper)
                or np.any(self.speed_limit <= 0) or np.any(self.acceleration_limit <= 0)
                or np.any(self.reference < self.lower) or np.any(self.reference > self.upper)
                or not self.evidence_id):
            raise ReferenceRejected('invalid_configuration')
        self.velocity = np.zeros(43)
        self.next_tick = 0
        config = dict(lower=self.lower.tolist(), upper=self.upper.tolist(),
            active=self.active.tolist(), speed=self.speed_limit.tolist(),
            acceleration=self.acceleration_limit.tolist(),
            error_lower=self.error_lower.tolist(), error_upper=self.error_upper.tolist(),
            evidence_id=self.evidence_id, dt=self.DT)
        self.config_sha256 = self._hash(config)

    @staticmethod
    def _hash(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()

    def snapshot(self):
        return dict(version=1, config_sha256=self.config_sha256,
                    next_tick=self.next_tick, reference=self.reference.tolist(),
                    velocity=self.velocity.tolist())

    def restore(self, state):
        if (set(state) != set(self.snapshot()) or state['version'] != 1
                or state['config_sha256'] != self.config_sha256
                or type(state['next_tick']) is not int or state['next_tick'] < 0):
            raise ReferenceRejected('checkpoint_schema')
        reference = vector(state['reference'], 'checkpoint_reference')
        velocity = vector(state['velocity'], 'checkpoint_velocity')
        if (np.any(reference < self.lower) or np.any(reference > self.upper)
                or np.any(np.abs(velocity) > self.speed_limit + 1e-12)
                or np.any(velocity[~self.active] != 0)):
            raise ReferenceRejected('checkpoint_bounds')
        self.reference, self.velocity = reference, velocity
        self.next_tick = state['next_tick']

    def preview(self, tick, observed_q, observed_dq, target):
        if type(tick) is not int or tick != self.next_tick:
            raise ReferenceRejected('nonsequential_tick')
        q, dq, target = [vector(v, n) for v, n in
                         [(observed_q, 'q'), (observed_dq, 'dq'), (target, 'target')]]
        if np.any(target < self.lower) or np.any(target > self.upper):
            raise ReferenceRejected('target_native_range')
        if np.any(np.abs(target[~self.active] - self.reference[~self.active]) > 1e-12):
            raise ReferenceRejected('inactive_target_changed')
        error = q - self.reference
        if np.any(self.active & ((error < self.error_lower - 1e-9) |
                                (error > self.error_upper + 1e-9))):
            raise ReferenceRejected('observed_tracking_budget')
        dt = self.DT
        velocity_lo = np.maximum(-self.speed_limit, self.velocity - self.acceleration_limit * dt)
        velocity_hi = np.minimum(self.speed_limit, self.velocity + self.acceleration_limit * dt)
        # Include the current state and one linear velocity extrapolation.
        extrapolated = q + dq * dt
        lower = np.maximum.reduce([self.lower, self.reference + velocity_lo * dt,
                                   q - self.error_upper, extrapolated - self.error_upper])
        upper = np.minimum.reduce([self.upper, self.reference + velocity_hi * dt,
                                   q - self.error_lower, extrapolated - self.error_lower])
        lower[~self.active] = upper[~self.active] = self.reference[~self.active]
        if np.any(lower > upper + 1e-12):
            raise ReferenceRejected('admissible_interval_empty')
        # Proportional approach avoids injecting the task planner's abrupt step.
        desired_velocity = np.clip(4. * (target - self.reference),
                                   -self.speed_limit, self.speed_limit)
        reference = np.clip(self.reference + desired_velocity * dt, lower, upper)
        velocity = (reference - self.reference) / dt
        diagnostics = dict(max_delta_rad=float(np.max(np.abs(reference - self.reference))),
            max_reference_speed=float(np.max(np.abs(velocity))),
            max_reference_acceleration=float(np.max(np.abs(velocity - self.velocity) / dt)),
            limited=bool(np.max(np.abs(reference - target)) > 1e-9),
            evidence_id=self.evidence_id, future_tracking_certified=False,
            hypothesis='constant measured velocity over one command interval',
            observed_error_rad=error.tolist())
        return Proposal(self._hash(self.snapshot()), tick, tuple(reference), tuple(velocity), diagnostics)

    def commit(self, proposal):
        if (not isinstance(proposal, Proposal) or proposal.tick != self.next_tick
                or proposal.before_sha256 != self._hash(self.snapshot())):
            raise ReferenceRejected('stale_or_foreign_proposal')
        reference, velocity = vector(proposal.reference, 'proposal_reference'), vector(proposal.velocity, 'proposal_velocity')
        if (np.any(reference < self.lower) or np.any(reference > self.upper)
                or np.any(np.abs(velocity) > self.speed_limit + 1e-9)
                or np.any(np.abs(velocity - self.velocity) > self.acceleration_limit * self.DT + 1e-9)
                or np.any(np.abs(reference - self.reference - velocity * self.DT) > 1e-12)
                or np.any(reference[~self.active] != self.reference[~self.active])):
            raise ReferenceRejected('proposal_constraints')
        self.reference, self.velocity = reference, velocity
        self.next_tick += 1
        return reference.copy(), copy.deepcopy(proposal.diagnostics)

    def step(self, tick, observed_q, observed_dq, target):
        return self.commit(self.preview(tick, observed_q, observed_dq, target))


class ObservedProgress:
    """Stable measured endpoint and a finite hold budget; reference progress is insufficient."""
    def __init__(self, position_tolerance, velocity_tolerance, stable_ticks=25, max_ticks=300):
        if position_tolerance <= 0 or velocity_tolerance <= 0 or not 0 < stable_ticks <= max_ticks:
            raise ValueError('progress_configuration')
        self.position_tolerance = float(position_tolerance)
        self.velocity_tolerance = float(velocity_tolerance)
        self.stable_ticks, self.max_ticks = int(stable_ticks), int(max_ticks)
        self.ticks = self.stable = 0

    def update(self, observed_error, observed_speed):
        if self.ticks >= self.max_ticks:
            raise ReferenceRejected('observed_progress_timeout')
        values = np.asarray([observed_error, observed_speed])
        if not np.isfinite(values).all() or np.any(values < 0):
            raise ReferenceRejected('progress_observation')
        self.ticks += 1
        ready = observed_error <= self.position_tolerance and observed_speed <= self.velocity_tolerance
        self.stable = self.stable + 1 if ready else 0
        return self.stable >= self.stable_ticks

    def snapshot(self):
        return dict(version=1, position_tolerance=self.position_tolerance,
                    velocity_tolerance=self.velocity_tolerance,
                    stable_ticks=self.stable_ticks, max_ticks=self.max_ticks,
                    ticks=self.ticks, stable=self.stable)

    def restore(self, state):
        expected = self.snapshot()
        if (set(state) != set(expected)
                or any(state[k] != expected[k] for k in
                       ['version', 'position_tolerance', 'velocity_tolerance', 'stable_ticks', 'max_ticks'])
                or any(type(state[k]) is not int for k in ['ticks', 'stable'])
                or not 0 <= state['stable'] <= state['ticks'] <= self.max_ticks):
            raise ReferenceRejected('progress_checkpoint')
        self.ticks, self.stable = state['ticks'], state['stable']
