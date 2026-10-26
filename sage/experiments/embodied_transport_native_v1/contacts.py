"""Rigid-flex-aware contact identity; never treat flex geom=-1 as a geom index."""

import numpy as np
import mujoco
from sage.experiments.embodied_carry_v1.grasp import group


def participant(model, contact, side):
    geom = int(contact.geom[side])
    flex = int(contact.flex[side])
    if geom >= 0:
        return {
            "name": model.geom(geom).name or "",
            "body": model.body(int(model.geom_bodyid[geom])).name,
            "geom": geom,
            "flex": -1,
        }
    if flex >= 0:
        body = int(model.flex_vertbodyid[model.flex_vertadr[flex]])
        return {
            "name": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_FLEX, flex),
            "body": model.body(body).name,
            "geom": -1,
            "flex": flex,
        }
    raise ValueError("contact has neither geom nor flex")


def contact_pair(model, contact):
    return [participant(model, contact, i) for i in (0, 1)]


def observe(mujoco, model, data):
    payload = model.body("payload").id
    wrist = model.body("right_wrist_yaw_link").id
    geom = model.geom("payload_geom").id
    contacts = []
    forces = {
        n: 0.0
        for n in ("source", "target", "thumb", "index", "middle", "palm", "other")
    }
    fixture_violation = scene_violation = False
    for i, c in enumerate(data.contact):
        pair = contact_pair(model, c)
        names = [p["name"] for p in pair]
        for side, p in enumerate(pair):
            if p["name"].startswith("scene_collision_"):
                scene_violation = True
            if p["name"] == "native_floor" and pair[1 - side]["body"] not in (
                "left_ankle_roll_link",
                "right_ankle_roll_link",
            ):
                scene_violation = True
        if any(n.startswith("task_") for n in names) and not any(
            p["geom"] == geom for p in pair
        ):
            fixture_violation = True
        if not any(p["geom"] == geom for p in pair):
            continue
        other = pair[1] if pair[0]["geom"] == geom else pair[0]
        name = other["name"]
        role = (
            "source"
            if name == "task_source_support"
            else "target" if name == "task_target_support" else group(other["body"])
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


def foot_metrics(mujoco, model, data):
    result = {}
    for side in ("left", "right"):
        body = model.body(f"{side}_ankle_roll_link").id
        geoms = np.flatnonzero(
            (model.geom_bodyid == body)
            & ((model.geom_contype | model.geom_conaffinity) != 0)
        )
        bottoms = []
        for geom in geoms:
            if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_SPHERE:
                extent_z = model.geom_size[geom, 0]
            elif model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_BOX:
                extent_z = (
                    np.abs(data.geom_xmat[geom].reshape(3, 3)[2])
                    @ model.geom_size[geom]
                )
            else:
                raise RuntimeError("unrecognized official sole primitive")
            bottoms.append(data.geom_xpos[geom, 2] - extent_z)
        if not bottoms:
            raise RuntimeError("official sole collision geometry missing")
        force_max = 0.0
        for i, c in enumerate(data.contact):
            pair = contact_pair(model, c)
            if any(
                p["geom"] in geoms and pair[1 - s]["name"] == "native_floor"
                for s, p in enumerate(pair)
            ):
                force = np.zeros(6)
                mujoco.mj_contactForce(model, data, i, force)
                force_max = max(force_max, float(np.linalg.norm(force[:3])))
        result[side] = {
            "sole_clearance_m": float(min(bottoms)),
            "ground_contact_force_max_n": force_max,
        }
    return result
