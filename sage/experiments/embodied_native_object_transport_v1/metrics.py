"""Native flex identities, actual object support and finite physical safety gates."""

import numpy as np
from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
from sage.experiments.embodied_carry_v1.grasp import group
from sage.experiments.embodied_native_walk_v1.preflight import soles

LIMITS = dict(
    max_penetration_m=0.01,
    max_contact_force_n=600.0,
    minimum_root_height_m=0.7,
    minimum_up=0.97,
    max_root_speed_m_s=1.5,
    max_root_acceleration_m_s2=50.0,
    max_root_angular_speed_rad_s=4.0,
    max_body_joint_speed_rad_s=20.0,
    max_body_joint_acceleration_rad_s2=2000.0,
    max_actual_joint_excess_rad=0.035,
    max_raw_target_projection_rad=0.035,
    maximum_goal_error_m=0.10,
    minimum_carry_distance_m=0.25,
)


def measure(mujoco, model, data, ids, before_velocity, case):
    obj = model.body("payload").id
    wrist = model.body("right_wrist_yaw_link").id
    payload_dof = int(model.joint("payload_free").dofadr[0])
    points = (
        np.asarray(case["mug_local_bounds_corners"]) @ data.xmat[obj].reshape(3, 3).T
        + data.xpos[obj]
    )
    heights = soles(mujoco, model, data)
    feet = {
        side: {"clearance_m": heights[side], "ground_force_n": 0.0}
        for side in ("left", "right")
    }
    forces = {k: 0.0 for k in ("desk", "thumb", "index", "middle", "palm", "other")}
    contacts, forbidden = [], []
    maximum_force = depth = hand_scene_force = 0.0
    for i, c in enumerate(data.contact):
        pair = contact_pair(model, c)
        f = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, f)
        force = float(np.linalg.norm(f[:3]))
        normal = max(0.0, float(f[0]))
        maximum_force = max(maximum_force, force)
        depth = max(depth, -float(c.dist))
        names = [p["name"] for p in pair]
        bodies = [p["body"] for p in pair]
        object_contact = "payload_surface" in names
        bad = False
        if object_contact:
            other = pair[1] if names[0] == "payload_surface" else pair[0]
            role = "desk" if other["body"] == "generated_desk" else group(other["body"])
            forces[role] += normal
            bad = role == "other"
        elif "native_floor" in names:
            side = next(
                (side for side in feet if side + "_ankle_roll_link" in bodies), None
            )
            bad = side is None
            if side:
                feet[side]["ground_force_n"] = max(feet[side]["ground_force_n"], normal)
        elif any(n.startswith("scene_collision_") for n in names):
            # Light incidental hand touch is recorded, not accepted as support.
            hand = any(b.startswith("right_hand_") for b in bodies)
            desk = "generated_desk" in bodies
            hand_scene_force += normal if hand and desk else 0.0
            bad = not (hand and desk and force <= 10.0)
        row = {
            "pair": pair,
            "normal_force_n": normal,
            "force_norm_n": force,
            "distance_m": float(c.dist),
            "forbidden": bool(bad),
        }
        contacts.append(row)
        if bad:
            forbidden.append(row)
    robot_dofs = ids["dof_ids"]
    acceleration = (data.qvel[:3] - np.asarray(before_velocity)[:3]) / 0.005
    joint_acc = (
        data.qvel[robot_dofs] - np.asarray(before_velocity)[robot_dofs]
    ) / 0.005
    actual = data.qpos[ids["qpos_ids"]]
    lo, hi = model.jnt_range[ids["joint_ids"]].T
    excess = float(max(0.0, np.max(lo - actual), np.max(actual - hi)))
    up = float(data.xmat[model.body("pelvis").id].reshape(3, 3)[2, 2])
    checks = {
        "finite": bool(
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and np.isfinite(data.ctrl).all()
        ),
        "no_external_force": not (
            np.any(data.xfrc_applied) or np.any(data.qfrc_applied)
        ),
        "no_forbidden_contact": not forbidden,
        "native_effort_limits": bool(
            np.all(data.ctrl >= model.actuator_ctrlrange[:, 0] - 1e-9)
            and np.all(data.ctrl <= model.actuator_ctrlrange[:, 1] + 1e-9)
        ),
        "height": bool(data.qpos[2] >= LIMITS["minimum_root_height_m"]),
        "upright": up >= LIMITS["minimum_up"],
        "penetration": depth <= LIMITS["max_penetration_m"],
        "contact_force": maximum_force <= LIMITS["max_contact_force_n"],
        "root_speed": float(np.linalg.norm(data.qvel[:3]))
        <= LIMITS["max_root_speed_m_s"],
        "root_acceleration": float(np.linalg.norm(acceleration))
        <= LIMITS["max_root_acceleration_m_s2"],
        "root_angular_speed": float(np.linalg.norm(data.qvel[3:6]))
        <= LIMITS["max_root_angular_speed_rad_s"],
        "joint_speed": float(np.max(np.abs(data.qvel[robot_dofs])))
        <= LIMITS["max_body_joint_speed_rad_s"],
        "joint_acceleration": float(np.max(np.abs(joint_acc)))
        <= LIMITS["max_body_joint_acceleration_rad_s2"],
        "actual_joint_excess": excess <= LIMITS["max_actual_joint_excess_rad"],
    }
    local = data.xmat[wrist].reshape(3, 3).T @ (data.xpos[obj] - data.xpos[wrist])
    return {
        "time_s": float(data.time),
        "root_m": data.qpos[:3].tolist(),
        "root_velocity_m_s": data.qvel[:3].tolist(),
        "up": up,
        "root_acceleration_m_s2": acceleration.tolist(),
        "maximum_joint_speed_rad_s": float(np.max(np.abs(data.qvel[robot_dofs]))),
        "maximum_joint_acceleration_rad_s2": float(np.max(np.abs(joint_acc))),
        "maximum_joint_excess_rad": excess,
        "penetration_m": depth,
        "maximum_contact_force_n": maximum_force,
        "feet": feet,
        "object_m": data.xpos[obj].tolist(),
        "object_bottom_m": float(points[:, 2].min()),
        "object_velocity_m_s": data.qvel[payload_dof : payload_dof + 3].tolist(),
        "object_local_m": local.tolist(),
        "object_rotation": data.xmat[obj].reshape(3, 3).tolist(),
        "forces": forces,
        "opposing": bool(
            forces["thumb"] > 0.01 and max(forces["index"], forces["middle"]) > 0.01
        ),
        "desk_supported": bool(forces["desk"] > 0.05),
        "hand_contact": bool(
            sum(forces[k] for k in ("thumb", "index", "middle", "palm")) > 0.02
        ),
        "hand_scene_force_n": hand_scene_force,
        "forbidden_contacts": len(forbidden),
        "contacts": contacts,
        "gates": {k: bool(v) for k, v in checks.items()},
        "safe": all(checks.values()),
    }
