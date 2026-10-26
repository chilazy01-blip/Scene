"""Keep the actual wrist withdrawn while reorienting, before lateral alignment."""

import numpy as np
from scipy.spatial.transform import Rotation
from .task_r5 import Task as ParentTask


class Task(ParentTask):
    LIMITS = {**ParentTask.LIMITS, "reach": 600}

    def update(self, frame, data, metrics):
        if self.stage != "reach":
            return super().update(frame, data, metrics)
        if self.failure or self.done:
            return
        if frame - self.stage_start > self.LIMITS["reach"]:
            self.failure = "reach_timeout"
            return
        wrist = self.model.body("right_wrist_yaw_link").id
        actual = data.xpos[wrist].copy()
        rotation = data.xmat[wrist].reshape(3, 3).copy()
        desired = np.array(self.case["desired_wrist_rotation"])
        grasp = np.array(metrics["world_position_m"]) - desired @ np.array(
            self.case["grasp_local_xyz_m"]
        )
        if self.sub_start is None:
            self.start_sub(
                "withdraw", frame, data, actual + [-0.16, 0.06, 0.15], rotation
            )
            return
        local_age = frame - self.sub_start
        if self.reach_subphase in ("withdraw", "orient_withdrawn"):
            goal = self.sub_goal
        elif self.reach_subphase == "preinsert":
            goal = grasp + [-0.10, 0, 0.01]
        else:
            goal = grasp
        target_R = self.sub_rotation if self.reach_subphase == "withdraw" else desired
        error = float(np.linalg.norm(goal - actual))
        angle = float(
            np.linalg.norm(Rotation.from_matrix(target_R.T @ rotation).as_rotvec())
        )
        if local_age >= 75 and local_age % 25 == 0:
            self.feedback(goal, target_R, actual, rotation)
            self.cartesian_goal(
                frame,
                data,
                goal + self.bias,
                target_R @ Rotation.from_rotvec(self.rotation_bias).as_matrix(),
                30,
            )
        ready = local_age >= 60 and error < 0.025 and angle < 0.15
        self.stable = self.stable + 1 if ready else 0
        if self.reach_subphase == "withdraw" and self.stable >= 5:
            self.start_sub("orient_withdrawn", frame, data, self.sub_goal, desired)
        elif self.reach_subphase == "orient_withdrawn" and self.stable >= 5:
            self.start_sub("preinsert", frame, data, grasp + [-0.10, 0, 0.01], desired)
        elif self.reach_subphase == "preinsert" and self.stable >= 5:
            self.start_sub("insert", frame, data, grasp, desired)
        elif self.reach_subphase == "insert":
            touching = metrics["hand_contact"] and error < 0.035 and angle < 0.18
            if metrics["source_supported"] and (touching or self.stable >= 10):
                self.rotation_bias[:] = 0
                self.transition("close", frame, metrics)
