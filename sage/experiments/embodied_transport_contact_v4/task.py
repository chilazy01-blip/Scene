"""Real compact-arm phase between verified lift and actual held walking."""

import numpy as np
from sage.experiments.embodied_transport_contact_v3.task import Task as ParentTask
from sage.experiments.embodied_transport_contact_v1.fast_kinematics import (
    solve,
    ARM_NAMES,
)
from sage.experiments.embodied_transport_hybrid_v3.control import ARM
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)


class Task(ParentTask):
    LIMITS = {**ParentTask.LIMITS, "tuck": 150}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.compact_ready = False

    def transition(self, stage, frame, metrics):
        if (
            stage == "carry"
            and self.case["task_mode"] == "full_transport"
            and not self.compact_ready
        ):
            stage = "tuck"
            self.world_path = None
        return super().transition(stage, frame, metrics)

    def begin_carry(self, frame, data):
        if self.stage == "tuck":
            return
        return super().begin_carry(frame, data)

    def update(self, frame, data, metrics):
        if self.stage != "tuck":
            return super().update(frame, data, metrics)
        if self.failure or self.done:
            return
        age = frame - self.stage_start
        if age > self.LIMITS["tuck"]:
            self.failure = "compact_load_timeout"
            return
        qids = np.array([self.model.joint(n).qposadr[0] for n in ARM_NAMES])
        if age == 1:
            seed = data.qpos.copy()
            seed[qids] = np.array(DEFAULT_ANGLES)[ARM]
            w = self.model.body("right_wrist_yaw_link").id
            goal = data.qpos[:3] + np.array(
                self.case["compact_wrist_relative_to_base_m"]
            )
            rotation = data.xmat[w].reshape(3, 3).copy()
            ik = solve(
                self.mujoco, self.model, seed, goal, rotation, max_evaluations=150
            )
            self.last_ik = ik
            if ik["position_error_m"] > 0.005 or ik["orientation_error_rad"] > 0.05:
                self.failure = "compact_load_ik_rejected"
                return
            self.reference_events.append(
                {
                    "kind": "compact_goal",
                    "frame": frame,
                    "relative_to_base_m": self.case["compact_wrist_relative_to_base_m"],
                    "goal_m": goal.tolist(),
                    "rotation": rotation.tolist(),
                    "angles_rad": ik["angles_rad"],
                }
            )
            self.arm_goal(frame, ik["angles_rad"], 100)
        slip = float(
            np.linalg.norm(np.array(metrics["local_position_m"]) - self.anchor)
        )
        self.max_slip = max(self.max_slip, slip)
        if slip > 0.03:
            self.failure = "compact_load_slip_rejected"
            return
        ready = (
            age >= 100
            and np.max(np.abs(data.qpos[qids] - self.q[frame, ARM + 7])) < 0.04
            and metrics["opposing"]
            and metrics["bottom_z_m"] >= self.case["support_top_m"] + 0.02
            and not metrics["source_supported"]
            and not metrics["target_supported"]
            and np.linalg.norm(data.qvel[:2]) < 0.04
        )
        self.stable = self.stable + 1 if ready else 0
        if self.stable >= 25:
            self.compact_ready = True
            self.transition("carry", frame, metrics)
            self.begin_carry(frame, data)
