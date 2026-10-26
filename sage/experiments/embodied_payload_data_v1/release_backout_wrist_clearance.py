"""Clear the unloaded left wrist from the shelf upright before backward stepping."""
import numpy as np
from scipy.spatial.transform import Rotation
from .release_backout_corridor import Recover as Original
from .withdrawal import Withdraw as OriginalWithdraw
from .geometry import smooth


class WristClearance(OriginalWithdraw):
    def __init__(self, m, c, robot, d, command, angle):
        super().__init__(m, c, robot, d, command)
        self.angle = angle

    def target(self, d):
        elapsed = d.time-self.start_time
        blend = smooth(elapsed/.8)
        angle = self.angle*smooth((elapsed-.15)/.4)
        poses = {}
        for side, (pos, rot) in self.poses.items():
            if side == 'left':
                rot = rot @ Rotation.from_euler('z', angle).as_matrix()
            poses[side] = (pos+self.direction[side]*(.03*blend), rot)
        seed = d.qpos.copy()
        seed[self.qmap[self.ids]] = self.last[self.ids]
        q, errors = self.arms.solve(seed, poses, iterations=20)
        delta = q[self.qmap[self.ids]]-self.last[self.ids]
        fraction = min(1., .04/max(float(abs(delta).max()), 1e-12))
        self.last[self.ids] += fraction*delta
        return self.last[self.upper].copy(), dict(
            withdraw_blend=float(blend), ik=errors, shared_fraction=fraction,
            retreat_m=.03*blend, left_palm_local_yaw=float(angle))


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.withdraw = WristClearance(m, c, robot, d, command, end_goal['withdraw_left_yaw'])
