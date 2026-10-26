"""The retained source's measured walk-to command and absorbing stop state."""
import numpy as np


class MeasuredWalkTo:
    def __init__(self, goal_xy, goal_yaw, tolerance=.07):
        self.goal = np.asarray(goal_xy, dtype=float)
        self.yaw = float(goal_yaw)
        self.tolerance = float(tolerance)
        self.stopped = False

    def command(self, data):
        if self.stopped:
            return np.zeros(3, dtype='f4')
        w, x, y, z = data.qpos[3:7]
        yaw = np.arctan2(2 * (w*z + x*y), 1 - 2 * (y*y + z*z))
        dx, dy = self.goal - data.qpos[:2]
        error = np.array([np.cos(yaw)*dx + np.sin(yaw)*dy,
                          -np.sin(yaw)*dx + np.cos(yaw)*dy])
        distance = np.linalg.norm(error)
        scale = error / max(distance, 1e-6)
        speed = max(min(2 * distance, .4), .30)
        yaw_error = np.arctan2(np.sin(self.yaw - yaw), np.cos(self.yaw - yaw))
        return np.clip([speed * scale[0], np.clip(speed * scale[1], -.3, .3),
                        np.clip(1.5 * yaw_error, -.6, .6)], [-.4, -.2, -.3], [.4, .2, .3]).astype('f4')

    def after_step(self, data):
        self.stopped |= bool(np.linalg.norm(self.goal - data.qpos[:2]) < self.tolerance)
