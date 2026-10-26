"""Top-aligned approach and contact-triggered closure; same physical gates."""

import numpy as np
from scipy.spatial.transform import Rotation
from .task import Task as BaseTask


class Task(BaseTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reach_subphase = "align_above"
        self.lower_start = None

    def update(self, frame, data, metrics):
        if self.stage != "reach":
            return super().update(frame, data, metrics)
        age = frame - self.stage_start
        if age > self.LIMITS["reach"]:
            self.failure = "reach_timeout"
            return
        wrist = self.model.body("right_wrist_yaw_link").id
        actual = data.xpos[wrist].copy()
        rotation = data.xmat[wrist].reshape(3, 3)
        desired = np.array(self.case["desired_wrist_rotation"])
        grasp = np.array(metrics["world_position_m"]) - desired @ np.array(
            self.case["grasp_local_xyz_m"]
        )
        orientation_error = float(
            np.linalg.norm(Rotation.from_matrix(desired.T @ rotation).as_rotvec())
        )
        if self.reach_subphase == "align_above":
            goal = grasp + np.array([0.0, 0.0, 0.08])
            if age == 1 or (age >= 75 and age % 25 == 0):
                if age >= 75:
                    self.bias = np.clip(self.bias + 0.35 * (goal - actual), -0.04, 0.04)
                self.ik(frame, data, goal, desired, 75 if age == 1 else 40)
            ready = (
                age >= 75
                and np.linalg.norm(goal - actual) < 0.02
                and orientation_error < 0.15
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 10:
                self.reach_subphase = "lower_to_grasp"
                self.lower_start = frame
                self.bias[:] = 0
                self.stable = 0
                self.ik(frame, data, grasp, desired, 75)
        else:
            lower_age = frame - self.lower_start
            if lower_age >= 75 and lower_age % 25 == 0:
                self.bias = np.clip(self.bias + 0.35 * (grasp - actual), -0.04, 0.04)
                self.ik(frame, data, grasp, desired, 40)
            error = float(np.linalg.norm(grasp - actual))
            contact_ready = (
                metrics["hand_contact"]
                and error < 0.03
                and orientation_error < 0.18
                and metrics["source_supported"]
            )
            exact_ready = (
                lower_age >= 75
                and error < 0.012
                and orientation_error < 0.15
                and metrics["source_supported"]
            )
            self.stable = self.stable + 1 if exact_ready else 0
            if contact_ready or self.stable >= 10:
                self.transition("close", frame, metrics)

    def snapshot(self, frame):
        result = super().snapshot(frame)
        result.update(reach_subphase=self.reach_subphase, lower_start=self.lower_start)
        return result
