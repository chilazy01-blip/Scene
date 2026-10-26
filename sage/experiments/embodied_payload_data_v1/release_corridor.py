"""Common-clock empty-hand joint path with a lateral clearance excursion."""
import numpy as np
from .release_recovery_joint_r2 import Recover as Original
from .geometry import smooth


class Recover(Original):
    def __init__(self, m, c, robot, d, command, plan):
        super().__init__(m, c, robot, d, command, plan['neutral_goal'])
        self.excursion = np.zeros(43)
        for name, value in plan['joint_excursion'].items():
            self.excursion[c['joint_names'].index(name)] = value

    def curve(self, clock):
        blend = smooth(clock)
        command = self.start + (self.end - self.start) * blend
        command += self.excursion * np.sin(np.pi * blend) ** 2
        return command, blend

    def target(self, d, current_height):
        if d.time - self.start_time < .6:
            return super().target(d, current_height)
        if self.start is None:
            self.start = self.last.copy()
            self.height0 = np.asarray(current_height).copy()
        proposed = min(1., self.clock + .02)
        command, blend = self.curve(proposed)
        if float(abs(command[self.arms] - self.last[self.arms]).max()) > .04:
            low, high = self.clock, proposed
            for _ in range(32):
                mid = (low + high) / 2
                q, _ = self.curve(mid)
                if float(abs(q[self.arms] - self.last[self.arms]).max()) <= .04:
                    low = mid
                else:
                    high = mid
            proposed = low
            command, blend = self.curve(proposed)
        assert float(abs(command[self.arms] - self.last[self.arms]).max()) <= .0401
        self.clock = proposed
        self.last = command
        height = self.height0 * (1 - blend) + self.height1 * blend
        return command[self.upper].copy(), height, dict(
            stage='collision_checked_joint_corridor', shared_clock=self.clock,
            blend=float(blend), ik_used=False,
            joint_excursion=self.excursion.tolist())
