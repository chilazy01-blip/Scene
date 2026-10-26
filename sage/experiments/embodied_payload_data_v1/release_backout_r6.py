"""After release, clear fingers relative to the body as the body retreats."""
import mujoco
from .release_backout import Recover as Original


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        self.reference_root = d.qpos[:7].copy()
        self.reference_data = mujoco.MjData(m)

    def target(self, d, current_height):
        if d.time - self.start_time < .6:
            # FK scratch state only. The live simulated state is never changed.
            # Unloaded palms need not remain at fixed world positions when the
            # body retreats; that constraint unnecessarily extends the arms.
            q = self.reference_data
            q.time = d.time
            q.qpos[:] = d.qpos
            q.qpos[:7] = self.reference_root
            upper, height, meta = super().target(q, current_height)
            meta['reference_frame'] = 'body_relative_after_verified_release'
            return upper, height, meta
        return super().target(d, current_height)
