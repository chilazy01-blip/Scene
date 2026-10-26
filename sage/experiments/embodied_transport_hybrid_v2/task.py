"""World-space right-arm servo, with a collision-checked top-down aperture path."""

import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_transport_hybrid_v1.task import Task as ParentTask
from sage.experiments.embodied_transport_v1.task import smooth
from sage.experiments.embodied_transport_v1.kinematics import solve
from .control import ARM
from pathlib import Path
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)


class Task(ParentTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.world_path = None
        self.servo_record = None
        self.clearance_waypoint = np.array(
            read_bound_json(Path(self.case["protocol_root"]) / "PREFLIGHT_SAFE.json")[
                "selected_waypoint"
            ]
        )

    def cartesian_goal(self, frame, data, goal, rotation, duration=60):
        wrist = self.model.body("right_wrist_yaw_link").id
        self.world_path = {
            "frame": frame,
            "duration": duration,
            "origin": data.xpos[wrist].copy(),
            "initial_R": data.xmat[wrist].reshape(3, 3).copy(),
            "goal": np.array(goal).copy(),
            "rotation": np.array(rotation).copy(),
        }
        super().cartesian_goal(frame, data, goal, rotation, duration)

    def arm_reference(self, frame, data):
        target = self.q[frame, 7:].astype(np.float64)
        self.servo_record = None
        if self.world_path is None or self.stage in (
            "approach",
            "source_stop",
            "carry",
            "target_stop",
        ):
            return target
        p = self.world_path
        weight = float(smooth((frame - p["frame"]) / p["duration"]))
        position = (1 - weight) * p["origin"] + weight * p["goal"]
        delta = Rotation.from_matrix(p["initial_R"].T @ p["rotation"]).as_rotvec()
        desired_R = p["initial_R"] @ Rotation.from_rotvec(delta * weight).as_matrix()
        ik = solve(
            self.mujoco, self.model, data.qpos, position, desired_R, max_evaluations=60
        )
        if ik["position_error_m"] > 0.005 or ik["orientation_error_rad"] > 0.05:
            self.failure = "world_arm_servo_ik_rejected"
            return target
        target[ARM] = ik["angles_rad"]
        self.servo_record = {
            "desired_position_m": position.tolist(),
            "desired_rotation": desired_R.tolist(),
            "angles_rad": ik["angles_rad"],
            "geometric_position_error_m": ik["position_error_m"],
            "geometric_orientation_error_rad": ik["orientation_error_rad"],
        }
        return target

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
        desired = np.eye(3)
        grasp = np.array(metrics["world_position_m"]) - np.array(
            self.case["grasp_local_xyz_m"]
        )
        if self.sub_start is None:
            self.start_sub(
                "withdraw", frame, data, actual + [-0.16, 0.06, 0.15], rotation
            )
            return
        local_age = frame - self.sub_start
        if self.reach_subphase in ("withdraw", "orient_withdrawn", "raise_clear"):
            goal = self.sub_goal
        else:
            goal = grasp + (
                [0, 0, 0.18] if self.reach_subphase == "overhead" else [0, 0, 0]
            )
        target_R = self.sub_rotation if self.reach_subphase == "withdraw" else desired
        error = float(np.linalg.norm(goal - actual))
        angle = float(
            np.linalg.norm(Rotation.from_matrix(target_R.T @ rotation).as_rotvec())
        )
        ready = local_age >= 60 and error < 0.012 and angle < 0.10
        self.stable = self.stable + 1 if ready else 0
        if self.stable >= 5:
            if self.reach_subphase == "withdraw":
                self.start_sub("orient_withdrawn", frame, data, self.sub_goal, desired)
            elif self.reach_subphase == "orient_withdrawn":
                self.start_sub(
                    "raise_clear", frame, data, self.clearance_waypoint, desired
                )
            elif self.reach_subphase == "raise_clear":
                self.start_sub("overhead", frame, data, grasp + [0, 0, 0.18], desired)
            elif self.reach_subphase == "overhead":
                self.start_sub("descend", frame, data, grasp, desired)
            elif self.reach_subphase == "descend" and metrics["source_supported"]:
                self.transition("close", frame, metrics)
