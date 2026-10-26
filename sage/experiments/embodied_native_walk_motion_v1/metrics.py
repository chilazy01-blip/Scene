"""Reconstruct native contact roles without aliasing flex contacts to geom[-1]."""

import numpy as np
from sage.experiments.embodied_native_walk_v1.preflight import soles
from sage.experiments.embodied_native_walk_v1.acceptance_v1 import LIMITS
from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    physical_guard,
    PHYSICAL_GATE_NAMES,
)


def measure(mujoco, model, data, ids, before, before_time, phase):
    safety = physical_guard(mujoco, model, data, model.body("pelvis").id, np.zeros(6))
    heights = soles(mujoco, model, data)
    feet = {
        s: {"clearance_m": heights[s], "ground_force_n": 0.0} for s in ("left", "right")
    }
    forbidden = []
    contacts = []
    for i, c in enumerate(data.contact):
        pair = contact_pair(model, c)
        force = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, force)
        names = [p["name"] for p in pair]
        bad = any(n.startswith("scene_collision_") for n in names)
        if "native_floor" in names:
            foot = next(
                (
                    s
                    for s in feet
                    if any(p["body"] == s + "_ankle_roll_link" for p in pair)
                ),
                None,
            )
            bad |= foot is None
            if foot:
                feet[foot]["ground_force_n"] = max(
                    feet[foot]["ground_force_n"], float(force[0])
                )
        contact = {
            "pair": pair,
            "distance_m": float(c.dist),
            "normal_force_n": float(force[0]),
            "forbidden": bool(bad),
        }
        contacts.append(contact)
        if bad:
            forbidden.append(contact)
    quality = bool(
        data.qpos[2] >= LIMITS["minimum_pelvis_m"]
        and safety["up_component"] >= LIMITS["minimum_up_component"]
    )
    controls = bool(
        np.isfinite(data.ctrl).all()
        and np.all(data.ctrl >= model.actuator_ctrlrange[:, 0] - 1e-9)
        and np.all(data.ctrl <= model.actuator_ctrlrange[:, 1] + 1e-9)
    )
    return {
        "time_before_s": float(before_time),
        "time_after_s": float(data.time),
        "phase": phase,
        "root_before_m": np.asarray(before[:3]).tolist(),
        "root_after_m": data.qpos[:3].tolist(),
        "root_velocity_m_s": data.qvel[:3].tolist(),
        "body_joint_velocity_rad_s": data.qvel[ids["dof_ids"]].tolist(),
        "feet": feet,
        "up_component": safety["up_component"],
        "penetration_m": safety["penetration_m"],
        "contact_force_n": safety["contact_force_n"],
        "forbidden_contacts": len(forbidden),
        "contacts": contacts,
        "xfrc_applied": data.xfrc_applied.tolist(),
        "qfrc_applied": data.qfrc_applied.tolist(),
        "physical_guard": safety,
        "quality_guard": quality,
        "all_motor_efforts_in_native_ranges": controls,
        "safe": bool(
            all(safety[k] for k in PHYSICAL_GATE_NAMES)
            and quality
            and controls
            and not forbidden
        ),
    }
