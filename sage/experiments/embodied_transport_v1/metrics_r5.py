"""Task contact roles, measured object clearance and unmodified body safety."""

import numpy as np
from sage.experiments.embodied_carry_v1.grasp import group


def observe(mujoco, model, data):
    payload = model.body("payload").id
    wrist = model.body("right_wrist_yaw_link").id
    geom = model.geom("payload_geom").id
    contacts = []
    forces = {
        "source": 0.0,
        "target": 0.0,
        "thumb": 0.0,
        "index": 0.0,
        "middle": 0.0,
        "palm": 0.0,
        "other": 0.0,
    }
    fixture_violation = False
    scene_violation = False
    for i, c in enumerate(data.contact):
        a, b = int(c.geom1), int(c.geom2)
        names = [model.geom(g).name for g in (a, b)]
        scene_violation |= any(
            n.startswith(("scene_proxy_", "room_wall_")) for n in names
        )
        if any(n.startswith("task_") for n in names) and geom not in (a, b):
            fixture_violation = True
        if geom not in (a, b):
            continue
        other = b if a == geom else a
        name = model.geom(other).name
        role = (
            "source"
            if name == "task_source_support"
            else (
                "target"
                if name == "task_target_support"
                else group(model.body(int(model.geom_bodyid[other])).name)
            )
        )
        f = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, f)
        forces[role] += max(0.0, float(f[0]))
        contacts.append(
            {
                "role": role,
                "other_geom": name,
                "normal_force_n": float(f[0]),
                "distance_m": float(c.dist),
            }
        )
    rotation = data.xmat[payload].reshape(3, 3)
    axis = rotation[:, 2]
    radius, half_height = model.geom_size[geom, :2]
    extent = half_height * abs(axis[2]) + radius * np.linalg.norm(axis[:2])
    local = data.xmat[wrist].reshape(3, 3).T @ (data.xpos[payload] - data.xpos[wrist])
    v = np.zeros(6)
    mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, payload, v, 0)
    return {
        "world_position_m": data.xpos[payload].tolist(),
        "local_position_m": local.tolist(),
        "local_rotation": (data.xmat[wrist].reshape(3, 3).T @ rotation).tolist(),
        "bottom_z_m": float(data.xpos[payload, 2] - extent),
        "linear_velocity_m_s": v[3:].tolist(),
        "contacts": contacts,
        "normal_forces_n": forces,
        "opposing": bool(
            forces["thumb"] > 0.01 and max(forces["index"], forces["middle"]) > 0.01
        ),
        "hand_contact": bool(
            sum(forces[n] for n in ("thumb", "index", "middle", "palm")) > 0.01
        ),
        "source_supported": forces["source"] > 0.02,
        "target_supported": forces["target"] > 0.02,
        "non_task_contact": forces["other"] > 0.01,
        "body_fixture_violation": bool(fixture_violation),
        "scene_violation": bool(scene_violation),
    }
