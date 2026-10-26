"""Ergonomic side approach with bounded six-dimensional reference feedback."""

import numpy as np
from scipy.spatial.transform import Rotation
from .task import Task as BaseTask, smooth
from .task_r4 import Task as CartesianTask


class Task(CartesianTask):
    LIMITS = {**BaseTask.LIMITS, "reach": 500}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rotation_bias = np.zeros(3)
        self.reach_subphase = "withdraw"

    def hand_fraction(self, frame):
        ready = self.case["ready_fraction"]
        if self.stage in ("approach", "source_stop", "reach"):
            return ready
        if self.stage == "close":
            return ready + (1 - ready) * float(smooth((frame - self.stage_start) / 50))
        return BaseTask.hand_fraction(self, frame)

    def feedback(self, goal, desired, actual, rotation):
        self.bias = np.clip(self.bias + 0.4 * (goal - actual), -0.06, 0.06)
        e = Rotation.from_matrix(desired.T @ rotation).as_rotvec()
        self.rotation_bias -= 0.4 * e
        n = np.linalg.norm(self.rotation_bias)
        if n > 0.35:
            self.rotation_bias *= 0.35 / n

    def start_sub(self, name, frame, data, goal, rotation):
        self.rotation_bias[:] = 0
        super().start_sub(name, frame, data, goal, rotation)

    def ik(self, frame, data, target, rotation, duration=50):
        wrist = self.model.body("right_wrist_yaw_link").id
        if frame - self.stage_start > 1:
            actual = data.xpos[wrist]
            actual_R = data.xmat[wrist].reshape(3, 3)
            # Base placement already updates position bias; add orientation only.
            e = Rotation.from_matrix(np.asarray(rotation).T @ actual_R).as_rotvec()
            self.rotation_bias = np.clip(self.rotation_bias - 0.3 * e, -0.25, 0.25)
        desired = (
            np.asarray(rotation) @ Rotation.from_rotvec(self.rotation_bias).as_matrix()
        )
        self.cartesian_goal(
            frame,
            data,
            np.asarray(target) + self.bias,
            desired,
            60 if duration > 50 else 30,
        )

    def update(self, frame, data, metrics):
        if self.failure or self.done:
            return
        age = frame - self.stage_start
        wrist = self.model.body("right_wrist_yaw_link").id
        actual = data.xpos[wrist].copy()
        rotation = data.xmat[wrist].reshape(3, 3).copy()
        if self.stage == "lift":
            if age > self.LIMITS["lift"]:
                self.failure = "lift_timeout"
                return
            if age == 1:
                self.rotation_bias[:] = 0
                self.ik(frame, data, self.lift_target, rotation, 50)
            slip = np.linalg.norm(np.array(metrics["local_position_m"]) - self.anchor)
            self.max_slip = max(self.max_slip, float(slip))
            if slip > 0.03:
                self.failure = "grip_slip_guard"
                return
            clear = metrics["bottom_z_m"] - self.case["support_top_m"]
            ready = (
                age >= 50
                and clear >= 0.02
                and not metrics["source_supported"]
                and not metrics["target_supported"]
                and metrics["opposing"]
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 25:
                self.minimum_source_clearance = clear
                self.transition("carry", frame, metrics)
                self.begin_carry(frame, data)
            return
        if self.stage != "reach":
            return BaseTask.update(self, frame, data, metrics)
        if age > self.LIMITS["reach"]:
            self.failure = "reach_timeout"
            return
        desired = np.array(self.case["desired_wrist_rotation"])
        grasp = np.array(metrics["world_position_m"]) - desired @ np.array(
            self.case["grasp_local_xyz_m"]
        )
        if self.sub_start is None:
            self.start_sub(
                "withdraw", frame, data, actual + [-0.09, 0.04, 0.07], rotation
            )
            return
        local_age = frame - self.sub_start
        goal = (
            self.sub_goal
            if self.reach_subphase == "withdraw"
            else grasp
            + (
                np.array([-0.08, 0, 0])
                if self.reach_subphase == "preinsert"
                else np.zeros(3)
            )
        )
        target_R = self.sub_rotation if self.reach_subphase == "withdraw" else desired
        error = float(np.linalg.norm(goal - actual))
        orientation_error = float(
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
        ready = local_age >= 60 and error < 0.025 and orientation_error < 0.15
        self.stable = self.stable + 1 if ready else 0
        if self.reach_subphase == "withdraw" and self.stable >= 5:
            self.start_sub("preinsert", frame, data, grasp + [-0.08, 0, 0], desired)
        elif self.reach_subphase == "preinsert" and self.stable >= 5:
            self.start_sub("insert", frame, data, grasp, desired)
        elif self.reach_subphase == "insert":
            touching = (
                metrics["hand_contact"] and error < 0.035 and orientation_error < 0.18
            )
            if metrics["source_supported"] and (touching or self.stable >= 10):
                self.rotation_bias[:] = 0
                self.transition("close", frame, metrics)
