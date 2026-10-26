"""Keep world feedback and draw unloaded palms back from the shelf uprights."""
import numpy as np
from .release_backout_world_hold import Recover as Original
from .withdrawal import Withdraw as OriginalWithdraw
from .geometry import smooth


class PalmClearance(OriginalWithdraw):
    def __init__(self, m, c, robot, d, command, backward, distance, start):
        super().__init__(m, c, robot, d, command)
        self.backward = backward
        self.distance = distance
        self.back_start = start

    def target(self, d):
        elapsed = d.time - self.start_time
        outward = .03 * smooth(elapsed / .8)
        retreat = self.distance * smooth((elapsed-self.back_start)/(.8-self.back_start))
        poses = {side: (pos+self.direction[side]*outward+self.backward*retreat, rot)
                 for side, (pos, rot) in self.poses.items()}
        seed = d.qpos.copy()
        seed[self.qmap[self.ids]] = self.last[self.ids]
        q, errors = self.arms.solve(seed, poses, iterations=20)
        delta = q[self.qmap[self.ids]] - self.last[self.ids]
        fraction = min(1., .04 / max(float(abs(delta).max()), 1e-12))
        self.last[self.ids] += fraction * delta
        return self.last[self.upper].copy(), dict(
            ik=errors, shared_fraction=fraction, outward_m=outward, backward_m=retreat)


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.withdraw = PalmClearance(m, c, robot, d, command, self.backward,
                                     end_goal['palm_back_m'], end_goal['palm_back_start_s'])
