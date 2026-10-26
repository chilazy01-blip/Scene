"""Measured body retreat plus a joint curve that clears the shelf uprights."""
import numpy as np
from .release_backout_r2 import Recover as Original
from .geometry import smooth


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.excursion = np.zeros(43)
        amplitude = end_goal['lateral_excursion_rad']
        self.excursion[c['joint_names'].index('left_shoulder_roll_joint')] = -amplitude
        self.excursion[c['joint_names'].index('right_shoulder_roll_joint')] = amplitude

    def curve(self, clock):
        blend = smooth(clock)
        q = self.start + (self.end - self.start) * blend
        q += self.excursion * np.sin(np.pi * blend) ** 2
        return q, blend

    def target(self, d, current_height):
        if d.time - self.start_time < .6:
            return super().target(d, current_height)
        if self.start is None:
            self.start = self.last.copy()
            self.height0 = np.asarray(current_height).copy()
        distance = float(np.dot(d.qpos[:3] - self.anchor, self.backward))
        allowed = max(smooth(self.clock), float(np.clip((distance-.025)/.055, 0., 1.)))
        proposed = min(1., self.clock+.025)
        low, high = self.clock, proposed
        for _ in range(32):
            mid = (low+high)/2
            q, blend = self.curve(mid)
            if blend <= allowed and float(abs(q[self.arms]-self.last[self.arms]).max()) <= .04:
                low = mid
            else:
                high = mid
        q, blend = self.curve(proposed)
        if blend > allowed or float(abs(q[self.arms]-self.last[self.arms]).max()) > .04:
            proposed = low
            q, blend = self.curve(proposed)
        assert float(abs(q[self.arms]-self.last[self.arms]).max()) <= .0401
        self.clock = proposed
        self.last = q
        height = self.height0*(1-blend)+self.height1*blend
        return q[self.upper].copy(), height, dict(
            stage='backout_clearance_gated_joint_corridor', shared_clock=self.clock,
            blend=float(blend), actual_backward_distance=distance,
            clearance_blend=allowed, target_body_retreat_m=.11,
            joint_excursion=self.excursion.tolist(), ik_used=False)
