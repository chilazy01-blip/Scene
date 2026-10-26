"""Discrete stopping-distance command limiter; no privileged-state correction."""
import numpy as np


class BrakingCommandLimiter:
    """Constrain commanded position, rate and acceleration from a stationary start.

    For candidate speed u, dt * sum(max(u-k*a*dt, 0)) is the travel
    including the candidate step and subsequent maximum braking. Its inverse
    is the minimum of finitely many affine bounds. Hard-bound viability is
    enforced independently of the requested target, which can change abruptly.
    This is a command-space guarantee, not a guarantee about physical contacts.
    """
    def __init__(self, initial_q, bounds, dt=.05, max_rate=.5, max_acceleration=1.):
        self.q = np.asarray(initial_q, dtype=float).copy()
        self.bounds = np.asarray(bounds, dtype=float).copy()
        self.dt, self.max_rate, self.max_acceleration = dt, max_rate, max_acceleration
        if self.q.shape != (7,) or self.bounds.shape != (7, 2):
            raise ValueError('invalid_limiter_shape')
        if not np.isfinite(self.q).all() or not np.isfinite(self.bounds).all():
            raise ValueError('nonfinite_limiter_initialization')
        if min(dt, max_rate, max_acceleration) <= 0 or np.any(self.bounds[:, 0] >= self.bounds[:, 1]):
            raise ValueError('invalid_limiter_bounds')
        if np.any(self.q < self.bounds[:, 0]) or np.any(self.q > self.bounds[:, 1]):
            raise ValueError('initial_command_outside_bounds')
        self.velocity = np.zeros(7)
        self.delta_v = max_acceleration * dt
        self.n = np.arange(1, int(np.ceil(max_rate / self.delta_v)) + 1, dtype=float)
        self.clipped_steps = 0

    def speed_cap(self, distance):
        distance = np.maximum(np.asarray(distance, dtype=float) - 1e-12, 0.)
        caps = distance[..., None] / (self.dt * self.n) + self.delta_v * (self.n - 1) / 2
        return np.minimum(self.max_rate, np.min(caps, axis=-1))

    def stopping_distance(self, speed):
        speed = np.abs(np.asarray(speed, dtype=float))
        return self.dt * np.maximum(speed[..., None] - self.delta_v * (self.n - 1), 0.).sum(axis=-1)

    def apply(self, raw):
        raw = np.asarray(raw, dtype=float)
        if raw.shape != (8,) or not np.isfinite(raw).all():
            raise ValueError('nonfinite_or_wrong_shape_policy_action')
        target = np.clip(raw[:7], self.bounds[:, 0], self.bounds[:, 1])
        error = target - self.q
        desired = np.sign(error) * self.speed_cap(np.abs(error))
        lower = np.maximum(self.velocity - self.delta_v, -self.speed_cap(self.q - self.bounds[:, 0]))
        upper = np.minimum(self.velocity + self.delta_v, self.speed_cap(self.bounds[:, 1] - self.q))
        if np.any(lower > upper + 1e-10):
            raise ValueError('no_feasible_braking_command')
        velocity = np.minimum(np.maximum(desired, lower), upper)
        q = self.q + self.dt * velocity
        if np.any(q < self.bounds[:, 0]) or np.any(q > self.bounds[:, 1]):
            raise ValueError('braking_command_outside_joint_bounds')
        if np.any(np.abs(velocity - self.velocity) > self.delta_v + 1e-10):
            raise ValueError('braking_command_acceleration_violation')
        action = np.r_[q, np.clip(raw[7], 0., .04)]
        self.clipped_steps += int(not np.allclose(action, raw, rtol=0, atol=1e-10))
        self.q, self.velocity = q, velocity
        return action
