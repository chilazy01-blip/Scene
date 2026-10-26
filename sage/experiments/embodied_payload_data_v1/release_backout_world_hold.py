"""Retain live world-palm feedback while waiting for actual backward clearance."""
import numpy as np
from .release_backout_corridor import Recover as Original


class Recover(Original):
    def target(self, d, current_height):
        distance = float(np.dot(d.qpos[:3] - self.anchor, self.backward))
        if self.clock == 0. and distance <= .025:
            upper, meta = self.withdraw.target(d)
            self.last[self.upper] = upper
            return upper, np.asarray(current_height).copy(), dict(
                stage='world_palm_feedback_until_body_clearance',
                actual_backward_distance=distance, **meta)
        return super().target(d, current_height)
