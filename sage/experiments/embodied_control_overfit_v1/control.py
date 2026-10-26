"""Separate target stopping from hard-bound braking in command space."""
import numpy as np
from sage.experiments.embodied_control_diag_v1.control import BrakingCommandLimiter


class DecomposedLimiter(BrakingCommandLimiter):
    def __init__(self, initial_q, bounds, mode='boundary', **kwargs):
        super().__init__(initial_q, bounds, **kwargs)
        if mode not in ('legacy', 'target_only', 'boundary', 'both'):
            raise ValueError(mode)
        self.mode = mode
        self.boundary_steps = 0

    def apply(self, raw):
        raw = np.asarray(raw, dtype=float)
        if raw.shape != (8,) or not np.isfinite(raw).all():
            raise ValueError('nonfinite_or_wrong_shape_policy_action')
        target = np.clip(raw[:7], self.bounds[:, 0], self.bounds[:, 1])
        error = target - self.q
        desired = (np.sign(error) * self.speed_cap(np.abs(error)) if self.mode in ('target_only', 'both')
                   else np.clip(error / self.dt, -self.max_rate, self.max_rate))
        lower, upper = self.velocity - self.delta_v, self.velocity + self.delta_v
        proposed = np.clip(desired, lower, upper)
        if self.mode in ('boundary', 'both'):
            lower = np.maximum(lower, -self.speed_cap(self.q - self.bounds[:, 0]))
            upper = np.minimum(upper, self.speed_cap(self.bounds[:, 1] - self.q))
        if np.any(lower > upper + 1e-10):
            raise ValueError('no_feasible_braking_command')
        velocity = np.minimum(np.maximum(desired, lower), upper)
        self.boundary_steps += int(np.any(np.abs(velocity - proposed) > 1e-10))
        q = self.q + self.dt * velocity
        if np.any(q < self.bounds[:, 0]) or np.any(q > self.bounds[:, 1]):
            raise ValueError('policy_command_reached_joint_boundary')
        if np.any(np.abs(velocity - self.velocity) > self.delta_v + 1e-10):
            raise ValueError('braking_command_acceleration_violation')
        action = np.r_[q, np.clip(raw[7], 0., .04)]
        self.clipped_steps += int(not np.allclose(action, raw, rtol=0, atol=1e-10))
        self.q, self.velocity = q, velocity
        return action
