"""Clear vertically first; then orient overhead and descend on reference IK knots."""

import numpy as np
from scipy.spatial.transform import Rotation
from .task import Task as BaseTask, smooth
from .kinematics import solve, ARM_NAMES
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)


class Task(BaseTask):
    LIMITS = {**BaseTask.LIMITS, "reach": 350}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.reach_subphase = "clear_vertical"
        self.sub_start = None
        self.sub_goal = None
        self.sub_rotation = None

    def cartesian_goal(self, frame, data, goal, rotation, duration=60):
        q = data.qpos.copy()
        qids = np.array([self.model.joint(n).qposadr[0] for n in ARM_NAMES], dtype=int)
        start = self.q[frame, self.arm + 7].copy()
        q[qids] = start
        fk = self.mujoco.MjData(self.model)
        fk.qpos[:] = q
        self.mujoco.mj_forward(self.model, fk)
        wrist = self.model.body("right_wrist_yaw_link").id
        origin = fk.xpos[wrist].copy()
        initial_R = fk.xmat[wrist].reshape(3, 3).copy()
        delta = Rotation.from_matrix(initial_R.T @ rotation).as_rotvec()
        knots = [(0, start.copy())]
        for offset in range(6, duration + 1, 6):
            w = float(smooth(offset / duration))
            position = (1 - w) * origin + w * np.array(goal)
            desired = initial_R @ Rotation.from_rotvec(delta * w).as_matrix()
            result = solve(
                self.mujoco, self.model, q, position, desired, max_evaluations=150
            )
            self.last_ik = result
            if (
                result["position_error_m"] > 0.005
                or result["orientation_error_rad"] > 0.05
            ):
                self.failure = "cartesian_reference_path_ik_rejected"
                return
            q[qids] = result["angles_rad"]
            knots.append((offset, np.array(result["angles_rad"])))
        offsets = np.array([x[0] for x in knots])
        angles = np.array([x[1] for x in knots])
        ages = np.arange(len(self.q) - frame)
        for j, index in enumerate(self.arm + 7):
            self.q[frame:, index] = np.interp(ages, offsets, angles[:, j])
        self.v = native._reference_velocities(self.q)
        self.reference_events.append(
            {
                "kind": "cartesian_arm_path",
                "frame": frame,
                "duration": duration,
                "goal_m": list(goal),
                "knots": [[int(t), a.tolist()] for t, a in knots],
            }
        )

    def start_sub(self, name, frame, data, goal, rotation):
        self.reach_subphase = name
        self.sub_start = frame
        self.sub_goal = np.array(goal).copy()
        self.sub_rotation = np.array(rotation).copy()
        self.stable = 0
        self.bias[:] = 0
        self.cartesian_goal(frame, data, self.sub_goal, self.sub_rotation)

    def update(self, frame, data, metrics):
        if self.stage != "reach":
            return super().update(frame, data, metrics)
        age = frame - self.stage_start
        if age > self.LIMITS["reach"]:
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
                "clear_vertical",
                frame,
                data,
                actual + np.array([0.0, 0.0, 0.13]),
                rotation,
            )
            return
        local_age = frame - self.sub_start
        goal = (
            self.sub_goal
            if self.reach_subphase == "clear_vertical"
            else grasp
            + (
                np.array([0.0, 0.0, 0.13])
                if self.reach_subphase == "align_overhead"
                else np.zeros(3)
            )
        )
        target_R = (
            self.sub_rotation if self.reach_subphase == "clear_vertical" else desired
        )
        error = float(np.linalg.norm(goal - actual))
        orientation_error = float(
            np.linalg.norm(Rotation.from_matrix(target_R.T @ rotation).as_rotvec())
        )
        if local_age >= 75 and local_age % 25 == 0:
            self.bias = np.clip(self.bias + 0.3 * (goal - actual), -0.04, 0.04)
            self.cartesian_goal(frame, data, goal + self.bias, target_R, 60)
        ready = local_age >= 60 and error < 0.02 and orientation_error < 0.15
        self.stable = self.stable + 1 if ready else 0
        if self.reach_subphase == "clear_vertical" and self.stable >= 5:
            self.start_sub(
                "align_overhead",
                frame,
                data,
                grasp + np.array([0.0, 0.0, 0.13]),
                desired,
            )
        elif self.reach_subphase == "align_overhead" and self.stable >= 5:
            self.start_sub("descend", frame, data, grasp, desired)
        elif self.reach_subphase == "descend":
            contact = (
                metrics["hand_contact"]
                and error < 0.035
                and orientation_error < 0.18
                and metrics["source_supported"]
            )
            if contact or (self.stable >= 10 and metrics["source_supported"]):
                self.transition("close", frame, metrics)

    def snapshot(self, frame):
        result = super().snapshot(frame)
        result.update(
            reach_subphase=self.reach_subphase,
            sub_start=self.sub_start,
            sub_goal_m=self.sub_goal.tolist() if self.sub_goal is not None else None,
        )
        return result
