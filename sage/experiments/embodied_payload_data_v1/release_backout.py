"""Move the free body away from the supported box before completing arm return."""
import numpy as np
from .release_recovery_joint_r2 import Recover as Original
from .geometry import smooth, yaw, wrap


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.anchor = d.qpos[:3].copy()
        self.heading = yaw(d.qpos[3:7])
        self.backward = np.array([-np.cos(self.heading), -np.sin(self.heading), 0.])

    def navigation(self, d):
        elapsed = d.time - self.start_time
        u = float(np.clip((elapsed - .2) / 1., 0., 1.))
        root = self.anchor + self.backward * (.12 * smooth(u))
        velocity = self.backward * (.12 * 30 * u**2 * (1-u)**2)
        angle = yaw(d.qpos[3:7])
        R = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
        nav = np.zeros(3)
        if .2 < elapsed < 1.4:
            brake = 1. - smooth((elapsed - 1.1) / .3)
            nav[:2] = brake * (R @ (velocity[:2] + 2.5 * (root[:2] - d.qpos[:2])))
            nav[2] = brake * np.clip(2. * wrap(self.heading - angle), -.3, .3)
            speed = np.linalg.norm(nav[:2])
            if speed > .24:
                nav[:2] *= .24 / speed
        return root, nav

    def target(self, d, current_height):
        elapsed = d.time - self.start_time
        if elapsed < .6:
            return super().target(d, current_height)
        if self.start is None:
            self.start = self.last.copy()
            self.height0 = np.asarray(current_height).copy()
        distance = float(np.dot(d.qpos[:3] - self.anchor, self.backward))
        # A common arm/waist/height clock can advance only as the real body
        # makes room. A target translation is never treated as achieved motion.
        clearance_blend = float(np.clip((distance - .025) / .055, 0., 1.))
        previous = smooth(self.clock)
        proposed = min(1., self.clock + .02)
        blend = max(previous, min(smooth(proposed), clearance_blend))
        desired = self.start + (self.end - self.start) * blend
        fraction = min(1., .04 / max(float(abs(desired[self.arms] - self.last[self.arms]).max()), 1e-12))
        blend = previous + fraction * (blend - previous)
        low, high = self.clock, proposed
        for _ in range(32):
            mid = (low + high) / 2
            if smooth(mid) < blend:
                low = mid
            else:
                high = mid
        self.clock = 1. if blend >= 1. else (low + high) / 2
        command = self.start + (self.end - self.start) * blend
        assert float(abs(command[self.arms] - self.last[self.arms]).max()) <= .0401
        self.last = command
        height = self.height0 * (1 - blend) + self.height1 * blend
        return command[self.upper].copy(), height, dict(
            stage='measured_backout_gated_joint_return', shared_clock=self.clock,
            blend=float(blend), actual_backward_distance=distance,
            clearance_blend=clearance_blend, shared_fraction=fraction,
            target_body_retreat_m=.12, body_motion_end_s=1.4,
            ik_used=False)
