"""Causal native-desk pickup/carry/place; only reference targets are modified."""

import numpy as np
from scipy.spatial.transform import Rotation
from .kinematics_r3 import IK, ARM_NAMES
from sage.experiments.embodied_locomotion_v1.reference import brake
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)


def smooth(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * t * (10 + t * (-15 + 6 * t))


class Task:
    def __init__(self, mujoco, model, case, baseq, basev):
        self.mujoco, self.model, self.case = mujoco, model, case
        self.baseq, self.basev = baseq.copy(), basev.copy()
        self.q = np.repeat(baseq[:1], 6000, axis=0)
        self.v = np.zeros((6000, 29))
        self.stage = "initial_stand"
        self.start = 0
        self.events = []
        self.failure = None
        self.done = False
        self.walk_start = None
        self.stop_frame = None
        self.path = None
        self.joint_path = None
        self.last_ik = None
        self.ik = IK(mujoco, model)
        self.armq = self.ik.qids
        self.wrist = model.body("right_wrist_yaw_link").id
        self.closure = 0.0
        self.anchor = None
        self.carry_origin = None
        self.object_lift_origin = None
        self.max_slip = 0.0
        self.held_samples = 0
        self.stable = 0
        self.carry_cycles = {"left": 0, "right": 0}
        self.foot_state = {"left": "unknown", "right": "unknown"}
        self.release_start = None

    def change(self, stage, tick, data, metrics):
        self.stage = stage
        self.start = tick
        self.stable = 0
        self.events.append(
            {
                "stage": stage,
                "tick": tick,
                "time_s": float(data.time),
                "root_m": data.qpos[:3].tolist(),
                "object_m": metrics["object_m"],
            }
        )

    def walk(self, tick, data, loaded):
        self.walk_start = tick
        q = self.baseq.copy()
        v = self.basev.copy()
        q[:, ARM + 7] = data.qpos[self.armq]
        v[:, ARM] = 0
        idx = np.minimum(np.arange(len(self.q) - tick), len(q) - 46)
        self.q[tick:] = q[idx]
        self.v[tick:] = v[idx]
        self.path = None
        self.joint_path = None

    def stop(self, tick):
        local = tick - self.walk_start
        q = self.q[self.walk_start : self.walk_start + len(self.baseq)].copy()
        v = self.v[self.walk_start : self.walk_start + len(self.baseq)].copy()
        q, v, stop = brake(q, v, local, duration=75)
        idx = np.minimum(np.arange(len(self.q) - self.walk_start), len(q) - 46)
        self.q[self.walk_start :] = q[idx]
        self.v[self.walk_start :] = v[idx]
        self.stop_frame = self.walk_start + stop

    def move(self, tick, data, goal, rotation, duration=65):
        self.joint_path = None
        self.path = {
            "tick": tick,
            "duration": duration,
            "origin": data.xpos[self.wrist].copy(),
            "initial_R": data.xmat[self.wrist].reshape(3, 3).copy(),
            "goal": np.array(goal),
            "R": np.array(rotation),
        }
        self.events.append(
            {
                "kind": "cartesian_path",
                "tick": tick,
                "origin": self.path["origin"].tolist(),
                "goal": list(goal),
                "rotation": np.asarray(rotation).tolist(),
                "duration": duration,
            }
        )
        self.synchronize(tick, data, force=True)

    def ready_arm(self, tick, data):
        from .metrics import measure
        goal = data.qpos[:3] + np.asarray(self.case["ready_arm_relative_m"])
        ik = self.ik.solve(data.qpos, goal, np.eye(3), max_evaluations=150)
        if ik["position_error_m"] > 0.010 or ik["orientation_error_rad"] > 0.05:
            self.failure = "ready_arm_unreachable"
            return
        origin = data.qpos[self.armq].copy()
        middle = np.array([-1.2, -0.2, 0.0, 1.6, 0.0, 0.0, 0.0])
        final = np.asarray(ik["angles_rad"])
        planning = self.mujoco.MjData(self.model)
        ids = native._model_ids(self.mujoco, self.model)
        bad = []
        for segment, (a, b) in enumerate(((origin, middle), (middle, final))):
            for f in np.linspace(0, 1, 31):
                planning.qpos[:] = data.qpos
                planning.qpos[self.armq] = (1-f)*a + f*b
                self.mujoco.mj_forward(self.model, planning)
                measured = measure(self.mujoco, self.model, planning, ids, np.zeros(self.model.nv), self.case)
                if measured["forbidden_contacts"] or measured["penetration_m"] > .01:
                    bad.append({"segment": segment, "fraction": float(f),
                                "penetration_m": measured["penetration_m"],
                                "forbidden_contacts": measured["forbidden_contacts"],
                                "contacts": [c for c in measured["contacts"] if c["forbidden"] or c["distance_m"] < -.01][:20]})
        self.events.append({"kind": "post_stop_raise_geometry", "tick": tick,
                            "physics_steps": 0, "sample_count": 62, "bad": bad})
        if bad:
            self.failure = "post_stop_raise_path_blocked"
            return
        self.path = None
        self.joint_path = {"tick": tick, "duration": 160, "target": final}
        ages = np.arange(len(self.q) - tick)
        first = smooth(ages / 80)[:, None]
        second = smooth((ages - 80) / 80)[:, None]
        self.q[tick:, ARM + 7] = np.where(
            (ages < 80)[:, None],
            (1-first)*origin + first*middle,
            (1-second)*middle + second*final)
        self.v = native._reference_velocities(self.q)
        self.events.append({"kind": "ready_joint_path", "tick": tick, "goal_m": goal.tolist(),
                            "middle_angles_rad": middle.tolist(), "angles_rad": final.tolist(),
                            "duration": 160})

    def desired(self, tick):
        p = self.path
        f = float(smooth((tick - p["tick"]) / p["duration"]))
        delta = Rotation.from_matrix(p["initial_R"].T @ p["R"]).as_rotvec()
        return (1 - f) * p["origin"] + f * p["goal"], p[
            "initial_R"
        ] @ Rotation.from_rotvec(delta * f).as_matrix()

    def synchronize(self, tick, data, force=False):
        if self.path is None or (not force and tick % 5):
            return
        seed = data.qpos.copy()
        knots = []
        for offset in range(0, 51, 5):
            pos, R = self.desired(tick + offset)
            ik = self.ik.solve(seed, pos, R, max_evaluations=60)
            self.last_ik = ik
            if ik["position_error_m"] > 0.010 or ik["orientation_error_rad"] > 0.05:
                self.failure = "arm_reference_unreachable"
                return
            seed[self.armq] = ik["angles_rad"]
            knots.append(ik["angles_rad"])
        end = min(len(self.q), tick + 100)
        ages = np.arange(end - tick)
        for j, index in enumerate(ARM + 7):
            self.q[tick:end, index] = np.interp(
                ages, np.arange(0, 51, 5), np.asarray(knots)[:, j]
            )
            self.q[end:, index] = knots[-1][j]
        self.v = native._reference_velocities(self.q)

    def arm_target(self, tick, data):
        target = self.q[tick, 7:].copy()
        if self.path is not None:
            pos, R = self.desired(tick)
            ik = self.ik.solve(data.qpos, pos, R, max_evaluations=60)
            self.last_ik = ik
            if ik["position_error_m"] > 0.010 or ik["orientation_error_rad"] > 0.05:
                self.failure = "arm_servo_unreachable"
                return target
            target[ARM] = ik["angles_rad"]
        return target

    def reached(self, tick, data):
        if self.joint_path is not None:
            p = self.joint_path
            return (
                tick >= p["tick"] + p["duration"]
                and np.max(np.abs(data.qpos[self.armq] - p["target"])) < 0.04
            )
        if self.path is None:
            return False
        pos, R = self.desired(tick)
        error = float(np.linalg.norm(data.xpos[self.wrist] - pos))
        angle = float(
            np.linalg.norm(
                Rotation.from_matrix(
                    R.T @ data.xmat[self.wrist].reshape(3, 3)
                ).as_rotvec()
            )
        )
        return (
            tick >= self.path["tick"] + self.path["duration"]
            and error < 0.015
            and angle < 0.12
        )

    def update(self, tick, data, m):
        age = tick - self.start
        if self.done or self.failure:
            return
        if age > self.case["stage_timeouts_ticks"].get(self.stage, 250):
            self.failure = self.stage + "_timeout"
            return
        speed = float(np.linalg.norm(data.qvel[:3]))
        source = np.asarray(self.case["source_object_xyz_m"])
        grasp = np.asarray(m["object_m"]) - np.asarray(self.case["grasp_local_xyz_m"])
        if (
            self.stage
            in (
                "initial_stand",
                "approach",
                "source_stop",
                "withdraw",
                "raise",
                "preinsert",
                "lower",
                "insert",
            )
            and np.linalg.norm(np.asarray(m["object_m"])[:2] - source[:2]) > 0.04
        ):
            self.failure = "premature_object_displacement"
            return
        if (
            self.stage in ("lift", "tuck", "carry", "target_stop", "place")
            and self.anchor is not None
        ):
            slip = float(np.linalg.norm(np.asarray(m["object_local_m"]) - self.anchor))
            self.max_slip = max(self.max_slip, slip)
            if slip > 0.04:
                self.failure = "object_slipped"
                return
        if self.stage == "initial_stand":
            if tick >= 150 and speed < 0.05:
                self.change("approach", tick, data, m)
                self.walk(tick, data, False)
        elif self.stage == "ready_arm" and self.reached(tick, data):
            self.change("preinsert", tick, data, m)
            self.move(
                tick,
                data,
                grasp + [-self.case["insertion_retreat_m"], 0, 0.10],
                np.eye(3),
                65,
            )
        elif self.stage == "approach":
            if (
                tick - self.walk_start >= 75
                and data.qpos[0] >= self.case["source_root_goal_xy_m"][0] - 0.20
            ):
                self.change("source_stop", tick, data, m)
                self.stop(tick)
        elif self.stage == "source_stop":
            ready = tick >= self.stop_frame and speed < 0.06
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 15:
                self.change("ready_arm", tick, data, m)
                self.ready_arm(tick, data)
        elif self.stage == "preinsert" and self.reached(tick, data):
            self.change("lower", tick, data, m)
            self.move(
                tick,
                data,
                grasp + [-self.case["insertion_retreat_m"], 0, 0],
                np.eye(3),
                65,
            )
        elif self.stage == "lower" and self.reached(tick, data):
            self.change("insert", tick, data, m)
            self.move(tick, data, grasp, np.eye(3), 80)
        elif self.stage == "insert" and self.reached(tick, data):
            self.change("close", tick, data, m)
        elif self.stage == "close":
            self.closure = self.case["grip_closure"] * float(smooth(age / 100))
            ready = age >= 100 and m["opposing"] and m["desk_supported"]
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 15:
                self.anchor = np.asarray(m["object_local_m"])
                self.change("lift", tick, data, m)
                self.move(
                    tick, data, data.xpos[self.wrist] + [0, 0, 0.13], np.eye(3), 90
                )
        elif self.stage == "lift":
            ready = (
                self.reached(tick, data)
                and not m["desk_supported"]
                and m["object_bottom_m"] > self.case["support_top_m"] + 0.025
                and m["opposing"]
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 25:
                self.object_lift_origin = np.asarray(m["object_m"])
                self.change("tuck", tick, data, m)
                self.move(
                    tick,
                    data,
                    data.qpos[:3] + np.asarray(self.case["ready_arm_relative_m"]),
                    np.eye(3),
                    90,
                )
        elif self.stage == "tuck" and self.reached(tick, data):
            if m["opposing"] and not m["desk_supported"]:
                self.change("carry", tick, data, m)
                self.carry_origin = data.qpos[:2].copy()
                self.walk(tick, data, True)
        elif self.stage == "carry":
            for side, foot in m["feet"].items():
                if foot["ground_force_n"] > 2:
                    if self.foot_state[side] == "swing":
                        self.carry_cycles[side] += 1
                    self.foot_state[side] = "stance"
                elif (
                    foot["ground_force_n"] <= 1
                    and foot["clearance_m"] >= 0.015
                    and self.foot_state[side] == "stance"
                ):
                    self.foot_state[side] = "swing"
            if (
                tick - self.walk_start >= 75
                and data.qpos[0] >= self.case["target_root_goal_xy_m"][0] - 0.20
            ):
                self.change("target_stop", tick, data, m)
                self.stop(tick)
        elif self.stage == "target_stop":
            ready = (
                tick >= self.stop_frame
                and speed < 0.06
                and data.qpos[0] - self.carry_origin[0] >= 0.25
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 15:
                self.change("place", tick, data, m)
                goal = np.asarray(self.case["target_object_xyz_m"]) - np.asarray(
                    m["object_local_m"]
                )
                self.move(tick, data, goal, np.eye(3), 120)
        elif self.stage == "place":
            ready = (
                self.reached(tick, data)
                and m["desk_supported"]
                and np.linalg.norm(
                    np.asarray(m["object_m"])[:2]
                    - np.asarray(self.case["target_object_xyz_m"])[:2]
                )
                < 0.10
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 20:
                self.change("release", tick, data, m)
        elif self.stage == "release":
            self.closure = self.case["grip_closure"] * (1 - float(smooth(age / 75)))
            if age >= 85 and m["desk_supported"]:
                self.change("retract", tick, data, m)
                self.move(
                    tick, data, data.xpos[self.wrist] + [-0.15, 0, 0.08], np.eye(3), 80
                )
        elif self.stage == "retract" and self.reached(tick, data):
            self.change("settle", tick, data, m)
        elif self.stage == "settle":
            ready = (
                m["desk_supported"]
                and not m["hand_contact"]
                and np.linalg.norm(m["object_velocity_m_s"]) < 0.02
                and speed < 0.06
            )
            self.stable = self.stable + 1 if ready else 0
            if self.stable >= 50:
                self.done = True
                self.change("done", tick, data, m)


