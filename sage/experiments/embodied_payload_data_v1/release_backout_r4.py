"""Separate open fingers sideways first, then withdraw palms and retreat the body."""
import numpy as np
from .release_backout_r2 import Recover as Original
from .withdrawal import Withdraw as OriginalWithdraw
from .geometry import smooth


class FingerClearance(OriginalWithdraw):
    def __init__(self, m, c, robot, d, command, backward):
        super().__init__(m, c, robot, d, command)
        self.backward = backward.copy()

    def target(self, d):
        t = d.time - self.start_time
        outward = .03 * smooth(t / .4)
        backward = .035 * smooth((t - .4) / .2)
        poses = {side: (pos + self.direction[side] * outward + self.backward * backward, rot)
                 for side, (pos, rot) in self.poses.items()}
        seed = d.qpos.copy()
        seed[self.qmap[self.ids]] = self.last[self.ids]
        q, errors = self.arms.solve(seed, poses, iterations=20)
        delta = q[self.qmap[self.ids]] - self.last[self.ids]
        fraction = min(1., .04 / max(float(abs(delta).max()), 1e-12))
        self.last[self.ids] += fraction * delta
        return self.last[self.upper].copy(), dict(
            stage='lateral_finger_clearance_then_palm_withdrawal',
            outward_m=outward, backward_m=backward, ik=errors,
            shared_fraction=fraction)


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.withdraw = FingerClearance(m, c, robot, d, command, self.backward)
