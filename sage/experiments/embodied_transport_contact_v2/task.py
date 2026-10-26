"""Separate release retreat: fixed wrist orientation, horizontal clearance first."""

import numpy as np
from sage.experiments.embodied_transport_contact_v1.task import Task as ParentTask


class Task(ParentTask):
    def ik(self, frame, data, target, rotation, duration=50):
        if self.stage == "retract":
            wrist = self.model.body("right_wrist_yaw_link").id
            actual = data.xpos[wrist].copy()
            R = data.xmat[wrist].reshape(3, 3).copy()
            self.rotation_bias[:] = 0
            self.bias[:] = 0
            self.cartesian_goal(
                frame, data, actual + np.array(self.case["retraction_vector_m"]), R, 50
            )
            return
        return super().ik(frame, data, target, rotation, duration)
