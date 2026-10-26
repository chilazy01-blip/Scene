"""Rebuild the future arm reference from actual posture before each policy step."""

import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_transport_hybrid_v2.task import Task as ParentTask
from .fast_kinematics import ARM_NAMES, solve
from sage.experiments.embodied_transport_v1.task import smooth
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from .control import ARM


class Task(ParentTask):
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
        self.reference_events.append(
            {
                "kind": "world_goal",
                "frame": frame,
                "duration": duration,
                "origin_m": self.world_path["origin"].tolist(),
                "goal_m": list(goal),
                "initial_rotation": self.world_path["initial_R"].tolist(),
                "rotation": np.array(rotation).tolist(),
            }
        )

    def synchronize_reference(self, frame, data):
        if self.world_path is None or self.stage in (
            "approach",
            "source_stop",
            "carry",
            "target_stop",
        ):
            return
        p = self.world_path
        delta = Rotation.from_matrix(p["initial_R"].T @ p["rotation"]).as_rotvec()
        q = data.qpos.copy()
        qids = np.array([self.model.joint(n).qposadr[0] for n in ARM_NAMES])
        knots = []
        for offset in range(0, 51, 5):
            weight = float(smooth((frame + offset - p["frame"]) / p["duration"]))
            position = (1 - weight) * p["origin"] + weight * p["goal"]
            desired = p["initial_R"] @ Rotation.from_rotvec(delta * weight).as_matrix()
            ik = solve(
                self.mujoco, self.model, q, position, desired, max_evaluations=80
            )
            self.last_ik = ik
            if ik["position_error_m"] > 0.005 or ik["orientation_error_rad"] > 0.05:
                self.failure = "state_coherent_reference_ik_rejected"
                return
            q[qids] = ik["angles_rad"]
            knots.append((offset, np.array(ik["angles_rad"])))
        ages = np.arange(len(self.q) - frame)
        offsets = np.array([x[0] for x in knots])
        angles = np.array([x[1] for x in knots])
        for j, index in enumerate(ARM + 7):
            self.q[frame:, index] = np.interp(ages, offsets, angles[:, j])
        self.v = native._reference_velocities(self.q)
        self.reference_events.append(
            {
                "kind": "world_reference_knots",
                "frame": frame,
                "knots": [[int(t), a.tolist()] for t, a in knots],
            }
        )

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
