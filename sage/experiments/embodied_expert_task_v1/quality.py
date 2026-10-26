"""Role-aware physics diagnostics; no dataset or task success is inferred here."""
import numpy as np
import mujoco


def names_and_roles(model, box_names):
    roles = []
    names = []
    for gid in range(model.ngeom):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, gid) or f"geom_{gid}"
        names.append(name)
        body = int(model.geom_bodyid[gid])
        ancestors = []
        while body:
            ancestors.append(mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body) or "")
            body = int(model.body_parentid[body])
        if name in box_names:
            role = "object"
        elif name == "floor":
            role = "floor"
        elif name.startswith("gripper0_"):
            role = "hand"
        elif name.startswith("robot0_"):
            role = "foot" if any("ankle_roll" in b or "foot" in b for b in ancestors) else "robot"
        else:
            role = "environment"
        roles.append(role)
    return names, roles


def kinematics(model, data, limits):
    q, v = data.qpos, data.qvel
    violations = []
    if not np.isfinite(q).all() or not np.isfinite(v).all():
        violations.append("nonfinite_state")
    w, x, y, z = q[3:7]
    tilt = float(np.arccos(np.clip(1 - 2*(x*x+y*y), -1, 1)))
    if tilt > limits["max_tilt_rad"]: violations.append("base_tilt")
    if q[2] < limits["min_height_m"]: violations.append("base_height")
    max_speed = float(np.max(np.abs(v)))
    if max_speed > limits["max_generalized_speed_sanity"]: violations.append("generalized_speed")
    excess = 0.0
    for j in range(model.njnt):
        if model.jnt_type[j] == mujoco.mjtJoint.mjJNT_HINGE and model.jnt_limited[j]:
            a = q[model.jnt_qposadr[j]]
            excess = max(excess, model.jnt_range[j,0]-a, a-model.jnt_range[j,1])
    if excess > limits["joint_limit_tolerance_rad"]: violations.append("joint_limit")
    return dict(time=float(data.time), base_height=float(q[2]), base_tilt=tilt,
                max_generalized_speed=max_speed, joint_limit_excess=float(excess), violations=violations)


def contacts(model, data, names, roles, limits):
    rows = []
    violations = []
    for i in range(data.ncon):
        c = data.contact[i]
        pair = {roles[c.geom1], roles[c.geom2]}
        robot = bool(pair & {"robot", "hand", "foot"})
        allowed = pair in ({"foot", "floor"}, {"hand", "object"}) or not robot
        force = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, force)
        loaded = float(np.linalg.norm(force[:3])) > 1e-4 or float(c.dist) < -1e-6
        row = dict(geoms=[names[c.geom1], names[c.geom2]], roles=[roles[c.geom1], roles[c.geom2]],
                   distance=float(c.dist), force=force.tolist(), allowed=allowed)
        rows.append(row)
        if not allowed and loaded: violations.append("forbidden_contact")
        if -float(c.dist) > limits["max_penetration_m"]: violations.append("penetration")
    return dict(contacts=rows, violations=sorted(set(violations)))
