"""Continuous measured-state pick/carry/place FSM; reference goals only."""

import numpy as np
from scipy.spatial.transform import Rotation
from .kinematics import solve, ARM_NAMES
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)
from sage.experiments.embodied_locomotion_v1.reference import walking


def smooth(u):
    u = np.clip(u, 0.0, 1.0)
    return u**3 * (10 + u * (-15 + 6 * u))


class Task:
    LIMITS = {
        "approach": 300,
        "source_stop": 150,
        "reach": 250,
        "close": 150,
        "lift": 150,
        "carry": 300,
        "target_stop": 150,
        "place": 250,
        "release": 100,
        "retract": 150,
        "settle": 100,
    }

    def __init__(self, planner, case, model, mujoco):
        gait, velocity, self.planner_metadata = walking(planner)
        self.gait = gait
        self.case = case
        self.model = model
        self.mujoco = mujoco
        self.q = np.concatenate([gait, np.repeat(gait[-1:], 2100 - len(gait), axis=0)])
        self.v = np.concatenate([velocity, np.zeros((2100 - len(velocity), 29))])
        self.arm = np.array(
            [list(SONIC_BODY_JOINT_ORDER).index(n) for n in ARM_NAMES], dtype=int
        )
        self.stage = "approach"
        self.stage_start = 0
        self.events = []
        self.reference_events = []
        self.stable = 0
        self.failure = None
        self.done = False
        self.walk_start = 0
        self.walk_start_pose = self.q[0].copy()
        self.walk_root_origin = np.array(case["start_xy_m"])
        self.walk_goal = np.array(case["source_root_goal_xy_m"])
        self.stop_frame = None
        self.anchor = None
        self.anchor_rotation = None
        self.bias = np.zeros(3)
        self.last_ik = None
        self.lift_target = None
        self.retract_target = None
        self.minimum_source_clearance = 0.0
        self.source_object_initial = np.array(case["source_object_xyz_m"])
        self.max_slip = 0.0

    def transition(self, stage, frame, metrics):
        self.events.append(
            {"from": self.stage, "to": stage, "frame": frame, "object": metrics}
        )
        self.stage = stage
        self.stage_start = frame
        self.stable = 0
        self.bias[:] = 0

    def arm_goal(self, frame, angles, duration=50):
        indices = self.arm + 7
        initial = self.q[frame, indices].copy()
        ages = np.arange(len(self.q) - frame) / duration
        w = smooth(ages)[:, None]
        self.q[frame:, indices] = (1 - w) * initial + w * np.asarray(angles)
        self.v = native._reference_velocities(self.q)
        self.reference_events.append(
            {
                "kind": "arm_goal",
                "frame": frame,
                "duration": duration,
                "angles_rad": list(angles),
            }
        )

    def ik(self, frame, data, target, rotation, duration=50):
        solution = solve(
            self.mujoco,
            self.model,
            data.qpos,
            np.asarray(target) + self.bias,
            rotation,
            max_evaluations=100,
        )
        self.last_ik = solution
        if (
            solution["position_error_m"] > 0.005
            or solution["orientation_error_rad"] > 0.05
        ):
            self.failure = "arm_reference_ik_out_of_workspace"
            return
        self.arm_goal(frame, solution["angles_rad"], duration)

    def brake(self, frame):
        duration = 55
        target = self.walk_start_pose.copy()
        target[:2] = self.q[frame + duration, :2]
        target[3:7] = self.q[frame, 3:7]
        original = self.q.copy()
        for index in range(frame, len(self.q)):
            weight = float(smooth((index - frame) / duration))
            self.q[index, :3] = (1 - weight) * original[index, :3] + weight * target[:3]
            self.q[index, 3:7] = native._quaternion_slerp(
                original[index, 3:7], target[3:7], weight
            )
            self.q[index, 7:] = (1 - weight) * original[index, 7:] + weight * target[7:]
        self.v = native._reference_velocities(self.q)
        self.v[frame + duration :] = 0
        self.stop_frame = frame + duration
        self.reference_events.append(
            {
                "kind": "brake",
                "frame": frame,
                "stop": self.stop_frame,
                "target": target.tolist(),
            }
        )

    def begin_carry(self, frame, data):
        current = self.q[frame].copy()
        tail = self.gait.copy()
        tail[:, :3] += current[:3] - tail[0, :3]
        tail[:, self.arm + 7] = current[self.arm + 7]
        for i in range(min(10, len(tail))):
            w = float(smooth(i / 8))
            tail[i, 7:] = (1 - w) * current[7:] + w * tail[i, 7:]
        count = min(len(tail), len(self.q) - frame)
        self.q[frame : frame + count] = tail[:count]
        self.q[frame + count :] = tail[count - 1]
        self.v = native._reference_velocities(self.q)
        self.walk_start = frame
        self.walk_start_pose = self.q[frame].copy()
        self.walk_root_origin = data.qpos[:2].copy()
        self.walk_goal = np.array(self.case["target_root_goal_xy_m"])
        self.stop_frame = None
        self.reference_events.append(
            {"kind": "begin_carry_walk", "frame": frame, "start_pose": current.tolist()}
        )

    def hand_fraction(self, frame):
        age = frame - self.stage_start
        if self.stage in (
            "approach",
            "source_stop",
            "reach",
            "retract",
            "settle",
            "done",
        ):
            return 0.0
        if self.stage == "close":
            return float(smooth(age / 50))
        if self.stage == "release":
            return 1 - float(smooth(age / 50))
        return 1.0

    def update(self, frame, data, metrics):
        if self.failure or self.done:
            return
        age = frame - self.stage_start
        if age > self.LIMITS[self.stage]:
            self.failure = self.stage + "_timeout"
            return
        wrist = self.model.body("right_wrist_yaw_link").id
        actual = data.xpos[wrist].copy()
        rotation = data.xmat[wrist].reshape(3, 3).copy()
        body_still = np.linalg.norm(data.qvel[:2]) < 0.04
        local = np.array(metrics["local_position_m"])
        if self.anchor is not None and self.stage in (
            "lift",
            "carry",
            "target_stop",
            "place",
        ):
            slip = float(np.linalg.norm(local - self.anchor))
            self.max_slip = max(self.max_slip, slip)
            if slip > 0.03:
                self.failure = "grip_slip_guard"
                return
        if self.stage in ("approach", "carry"):
            remaining = float(self.walk_goal[0] - data.qpos[0])
            if frame - self.walk_start >= 75 and remaining <= 0.16:
                self.brake(frame)
                self.transition(
                    "source_stop" if self.stage == "approach" else "target_stop",
                    frame,
                    metrics,
                )
        elif self.stage in ("source_stop", "target_stop"):
            ready = (
                frame >= self.stop_frame + 25
                and body_still
                and np.linalg.norm(data.qpos[:2] - self.walk_goal) < 0.15
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 25:
                self.transition(
                    "reach" if self.stage == "source_stop" else "place", frame, metrics
                )
        elif self.stage == "reach":
            desired = np.array(self.case["desired_wrist_rotation"])
            goal = np.array(metrics["world_position_m"]) - desired @ np.array(
                self.case["grasp_local_xyz_m"]
            )
            position_error = float(np.linalg.norm(goal - actual))
            orientation_error = float(
                np.linalg.norm(Rotation.from_matrix(desired.T @ rotation).as_rotvec())
            )
            if age == 1 or (age >= 75 and age % 25 == 0):
                if age >= 75:
                    self.bias = np.clip(self.bias + 0.35 * (goal - actual), -0.04, 0.04)
                self.ik(frame, data, goal, desired, 75 if age == 1 else 40)
            ready = (
                age >= 75
                and position_error < 0.012
                and orientation_error < 0.15
                and metrics["source_supported"]
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 10:
                self.transition("close", frame, metrics)
        elif self.stage == "close":
            if age == 50:
                self.anchor = local.copy()
                self.anchor_rotation = np.array(metrics["local_rotation"])
                self.reference_events.append(
                    {
                        "kind": "grip_anchor",
                        "frame": frame,
                        "local_position_m": local.tolist(),
                        "local_rotation": self.anchor_rotation.tolist(),
                    }
                )
            ready = (
                age >= 50
                and metrics["opposing"]
                and self.anchor is not None
                and np.linalg.norm(local - self.anchor) < 0.03
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 25:
                self.lift_target = actual + np.array([0.0, 0.0, 0.08])
                self.transition("lift", frame, metrics)
        elif self.stage == "lift":
            if age == 1:
                self.ik(frame, data, self.lift_target, rotation, 50)
            clear = metrics["bottom_z_m"] - 0.65
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
        elif self.stage == "place":
            desired = self.anchor_rotation.T
            center = np.array(self.case["target_object_xyz_m"])
            center[2] += 0.003 - min(0.013, max(0, age - 75) * 0.02 * 0.005)
            goal = center - desired @ self.anchor
            if age == 1 or (age >= 75 and age % 20 == 0):
                if age >= 75:
                    self.bias = np.clip(self.bias + 0.25 * (goal - actual), -0.04, 0.04)
                self.ik(frame, data, goal, desired, 75 if age == 1 else 30)
            ready = (
                age >= 75
                and metrics["normal_forces_n"]["target"] > 0.15
                and np.linalg.norm(metrics["linear_velocity_m_s"]) < 0.03
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 10:
                self.transition("release", frame, metrics)
        elif self.stage == "release":
            if age >= 60:
                self.retract_target = actual + np.array([-0.07, 0.0, 0.07])
                self.transition("retract", frame, metrics)
        elif self.stage == "retract":
            if age == 1:
                self.ik(frame, data, self.retract_target, rotation, 50)
            if age >= 65 and not metrics["hand_contact"]:
                self.transition("settle", frame, metrics)
        elif self.stage == "settle":
            ready = (
                metrics["normal_forces_n"]["target"] > 0.15
                and not metrics["hand_contact"]
                and np.linalg.norm(metrics["linear_velocity_m_s"]) < 0.02
                and np.linalg.norm(
                    np.array(metrics["world_position_m"])[:2]
                    - np.array(self.case["target_object_xyz_m"])[:2]
                )
                < 0.04
                and body_still
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 25:
                self.transition("done", frame, metrics)
                self.done = True

    def snapshot(self, frame):
        return {
            "stage": self.stage,
            "stage_start": self.stage_start,
            "age_ticks": frame - self.stage_start,
            "hand_closure_fraction": self.hand_fraction(frame),
            "stable_control_ticks": self.stable,
            "failure": self.failure,
            "done": self.done,
            "last_ik": self.last_ik,
            "anchor_local_xyz_m": (
                self.anchor.tolist() if self.anchor is not None else None
            ),
            "max_retention_slip_m": self.max_slip,
        }
