"""A declared, one-shot acquisition anchor; no writes to object state."""

import numpy as np
from sage.experiments.embodied_carry_v1.control import reference, setup, apply
from sage.experiments.embodied_carry_v1.grasp import payload_metrics
from sage.experiments.embodied_locomotion_v1.metrics import accept


class GripTracker:
    def __init__(self, protocol, initial_local):
        self.protocol = protocol
        self.initial = np.asarray(initial_local).copy()
        self.previous = self.initial.copy()
        self.anchor = None
        self.anchor_rotation = None
        self.consecutive = 0

    def observe(self, mujoco, model, data, step):
        result = payload_metrics(mujoco, model, data)
        local = np.asarray(result["local_position_m"])
        wrist = model.body("right_wrist_yaw_link").id
        payload = model.body("payload").id
        rotation = data.xmat[wrist].reshape(3, 3).T @ data.xmat[payload].reshape(3, 3)
        speed = float(np.linalg.norm(local - self.previous) / model.opt.timestep)
        self.previous = local.copy()
        if step == self.protocol["anchor_physics_step"]:
            if self.anchor is not None:
                raise RuntimeError("grip anchor must never be moved")
            self.anchor = local.copy()
            self.anchor_rotation = rotation.copy()
        slip = (
            float(np.linalg.norm(local - self.anchor))
            if self.anchor is not None
            else 0.0
        )
        angle = (
            float(
                np.arccos(
                    np.clip(
                        (np.trace(self.anchor_rotation.T @ rotation) - 1) / 2, -1, 1
                    )
                )
            )
            if self.anchor is not None
            else 0.0
        )
        acquired = (
            self.anchor is not None and step > self.protocol["anchor_physics_step"]
        )
        initial_shift = float(np.linalg.norm(local - self.initial))
        held = (
            acquired
            and result["opposing_finger_contact"]
            and not result["non_hand_contact"]
            and result["height_m"] >= 0.25
            and slip <= 0.03
            and angle <= np.pi / 6
        )
        stable = held and speed <= self.protocol["qualification_max_relative_speed_m_s"]
        self.consecutive = self.consecutive + 1 if stable else 0
        rejected = (
            result["non_hand_contact"]
            or result["height_m"] < 0.25
            or initial_shift > self.protocol["max_acquisition_displacement_m"]
            or (acquired and (slip > 0.03 or angle > np.pi / 6))
        )
        result.update(
            held=bool(held),
            qualification_stable=bool(stable),
            phase="retention" if acquired else "acquisition",
            relative_position_error_m=slip,
            initial_relative_position_error_m=initial_shift,
            relative_rotation_error_rad=angle,
            relative_speed_m_s=speed,
            anchor_local_xyz_m=(
                self.anchor.tolist() if self.anchor is not None else None
            ),
            anchor_rotation=(
                self.anchor_rotation.tolist()
                if self.anchor_rotation is not None
                else None
            ),
            anchor_physics_step=self.protocol["anchor_physics_step"],
            guard_rejected=bool(rejected),
        )
        return result


def acceptance(records, budget, case):
    rows = [r for r in records if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in rows for s in r["substeps"]]
    if not samples:
        return {"passed": False, "gates": {}, "metrics": {}}
    held = sum(s["payload"]["held"] for s in samples) / len(samples)
    slip = max(s["payload"]["relative_position_error_m"] for s in samples)
    angle = max(s["payload"]["relative_rotation_error_rad"] for s in samples)
    tail = samples[-200:]
    origin = np.asarray(tail[0]["full_qpos_before"][:2])
    drift = max(
        float(np.linalg.norm(np.asarray(s["full_qpos_after"][:2]) - origin))
        for s in tail
    )
    speed = max(float(np.linalg.norm(s["root_velocity_after_m_s"][:2])) for s in tail)
    joint_rms = max(
        float(np.sqrt(np.mean(np.square(s["body_velocity_after_rad_s"])))) for s in tail
    )
    both = sum(
        all(
            s["feet"][side]["ground_contact_force_max_n"] > 2
            for side in ("left", "right")
        )
        for s in tail
    ) / len(tail)
    gates = {
        "complete_protocol": len(rows) == budget and len(samples) == budget * 4,
        "contact_supported_retention": held >= 0.9,
        "relative_slip": slip <= 0.03,
        "relative_rotation": angle <= np.pi / 6,
        "no_non_hand_support": not any(
            s["payload"]["non_hand_contact"] for s in samples
        ),
        "object_above_floor": min(s["payload"]["height_m"] for s in samples) >= 0.25,
        "no_pelvis_support": all(
            not s["support_enabled"] and not any(s["support_wrench"]) for s in samples
        ),
        "upright_quality": min(s["up_component"] for s in samples) >= 0.97
        and min(s["pelvis_height_m"] for s in samples) >= 0.7,
    }
    if case["carry_mode"] == "standing":
        gates["standing_hold_quality"] = (
            drift <= 0.02 and speed <= 0.08 and joint_rms <= 0.6 and both >= 0.9
        )
    elif budget > 100:
        gates["locomotion_and_stop"] = accept(records, budget, case)["passed"]
    else:
        # Two seconds establishes safe retention, not completion of the stop task.
        gates["walking_short_is_safety_not_full_task"] = True
    return {
        "passed": bool(all(gates.values())),
        "gates": gates,
        "metrics": {
            "held_contact_fraction": held,
            "max_relative_slip_m": slip,
            "max_relative_rotation_rad": angle,
            "active_steps": len(samples),
            "last_second_drift_m": drift,
            "last_second_speed_m_s": speed,
            "last_second_joint_rms": joint_rms,
            "last_second_double_support_fraction": both,
        },
        "preloaded_grasp_not_pickup": True,
        "acquisition_and_retention_separate": True,
    }
