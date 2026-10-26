"""Zero-step geometry/contact preflight; does not qualify dynamic standing."""

import argparse
from pathlib import Path
import math
import numpy as np
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    physical_guard,
    PHYSICAL_GATE_NAMES,
)


def authorize(root):
    p = read_bound_json(root / "PLAN.json")
    for b in [
        p["scene"],
        p["canonical_xml"],
        p["cache"],
        *p["dependencies"].values(),
        *p["reused_frozen_dependencies"].values(),
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("frozen native scene dependency changed")
    return p


def soles(mujoco, model, data):
    out = {}
    for side in ("left", "right"):
        body = model.body(side + "_ankle_roll_link").id
        ids = np.flatnonzero(
            (model.geom_bodyid == body)
            & ((model.geom_contype | model.geom_conaffinity) != 0)
        )
        lower = []
        for g in ids:
            if model.geom_type[g] != mujoco.mjtGeom.mjGEOM_BOX:
                raise ValueError("official sole primitive changed")
            extent = np.abs(data.geom_xmat[g].reshape(3, 3)[2]) @ model.geom_size[g]
            lower.append(float(data.geom_xpos[g, 2] - extent))
        if not lower:
            raise ValueError("no official foot collider")
        out[side] = min(lower)
    return out


def initial_state(mujoco, model, condition):
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    data.qpos[ids["qpos_ids"]] = DEFAULT_ANGLES
    data.qpos[:2] = condition["start_xy_m"]
    yaw = math.radians(condition["start_yaw_deg"])
    data.qpos[3:7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
    mujoco.mj_kinematics(model, data)
    heights = soles(mujoco, model, data)
    # Initial placement only, before any integration: put the native sole at native floor z=0.
    data.qpos[2] -= min(heights.values()) + 0.0001
    mujoco.mj_forward(model, data)
    return data


def contact_roles(mujoco, model, data):
    out = []
    for i, c in enumerate(data.contact):
        pair = contact_pair(model, c)
        force = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, force)
        floor = next((p for p in pair if p["name"] == "native_floor"), None)
        allowed = bool(
            floor
            and any(
                p["body"] in ("left_ankle_roll_link", "right_ankle_roll_link")
                for p in pair
            )
        )
        dynamic = any(model.body_treeid[model.body(p["body"]).id] >= 0 for p in pair)
        out.append(
            {
                "pair": pair,
                "distance_m": float(c.dist),
                "normal_force_n": float(force[0]),
                "allowed_foot_floor": allowed,
                "both_fixed": not dynamic,
            }
        )
    return out


def corridor(scene, condition, distance):
    yaw = math.radians(condition["start_yaw_deg"])
    direction = np.array([math.cos(yaw), math.sin(yaw)])
    start = np.array(condition["start_xy_m"])
    end = start + direction * distance
    clearance = 100.0
    for t in np.linspace(0, 1, 101):
        xy = start + t * (end - start)
        clearance = min(
            clearance,
            xy[0],
            xy[1],
            scene["room"]["width"] - xy[0],
            scene["room"]["length"] - xy[1],
        )
        for obj in scene["obstacles"]:
            a = obj["yaw_rad"]
            c, s = math.cos(a), math.sin(a)
            local = np.array([[c, s], [-s, c]]) @ (xy - np.array(obj["center"][:2]))
            d = np.linalg.norm(
                np.maximum(np.abs(local) - np.array(obj["dimensions"][:2]) / 2, 0)
            )
            clearance = min(clearance, float(d))
    return float(clearance)


def run(root):
    import mujoco
    import trimesh

    p = authorize(root)
    scene = read_bound_json(root / "model/SCENE.json")
    if (root / "GEOMETRY_PREFLIGHT.json").exists():
        raise FileExistsError("preflight already exists")
    model = load_model(scene["model"]["path"])
    floor_id = model.geom("native_floor").id
    assert model.geom_type[floor_id] == mujoco.mjtGeom.mjGEOM_BOX
    assert not any(
        (model.body(i).name or "").startswith("task_")
        or model.body(i).name == "payload"
        for i in range(model.nbody)
    )
    coverage = [
        {
            "visual_geom": "scene_visual_0_0",
            "collision": "native_floor",
            "mode": "exact same-solid cuboid, no extra ground",
            "source": scene["native_floor"]["source"],
            "passed": scene["native_floor"]["recognition"]["same_solid_as_source"],
        }
    ]
    for surface in scene["native_collision_surfaces"]:
        mesh = trimesh.load(surface["source"]["path"], force="mesh", process=False)
        f = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_FLEX, surface["name"])
        a = int(model.flex_vertadr[f])
        n = int(model.flex_vertnum[f])
        e = int(model.flex_elemdataadr[f])
        t = int(model.flex_elemnum[f])
        vertices = model.flex_vert[a : a + n]
        faces = model.flex_elem[e : e + t * 3].reshape(-1, 3)
        error = float(np.max(np.abs(vertices - np.asarray(mesh.vertices))))
        ok = bool(
            model.flex_rigid[f]
            and model.flex_contype[f] == 2
            and model.flex_conaffinity[f] == 1
            and error < 1e-9
            and np.array_equal(faces, mesh.faces)
        )
        coverage.append(
            {
                "visual_geom": surface["visual_geom"],
                "collision": surface["name"],
                "source": surface["source"],
                "passed": ok,
                "vertices": n,
                "triangles": t,
                "maximum_vertex_error_m": error,
                "mode": "all native triangles, fixed rigid,1mm radius",
            }
        )
    conditions = []
    for condition in p["conditions_to_preflight"]:
        data = initial_state(mujoco, model, condition)
        q0 = data.qpos.copy()
        contacts = contact_roles(mujoco, model, data)
        guard = physical_guard(
            mujoco, model, data, model.body("pelvis").id, np.zeros(6)
        )
        radius = corridor(
            scene,
            condition,
            p["route_goal_distance_m"] + p["route_extra_stop_envelope_m"],
        )
        swept_ok = True
        worst_depth = 0.0
        bad = []
        yaw = math.radians(condition["start_yaw_deg"])
        direction = np.array([math.cos(yaw), math.sin(yaw)])
        for sample, distance in enumerate(
            np.linspace(
                0, p["route_goal_distance_m"] + p["route_extra_stop_envelope_m"], 101
            )
        ):
            data.qpos[:] = q0
            data.qpos[:2] += direction * distance
            data.qvel[:] = 0
            mujoco.mj_forward(model, data)
            roles = contact_roles(mujoco, model, data)
            forbidden = [c for c in roles if not c["allowed_foot_floor"]]
            if forbidden:
                bad.append(
                    {
                        "sample": sample,
                        "distance_m": float(distance),
                        "contacts": forbidden,
                    }
                )
            swept_ok &= not forbidden
            worst_depth = max(
                worst_depth, max((max(0, -c["distance_m"]) for c in roles), default=0)
            )
        gates = {k: guard[k] for k in PHYSICAL_GATE_NAMES}
        gates.update(
            native_corridor_radius=radius >= p["minimum_corridor_radius_m"],
            no_nonfoot_contacts=all(c["allowed_foot_floor"] for c in contacts),
            initial_left_and_right_support=all(
                any(
                    c["allowed_foot_floor"]
                    and c["normal_force_n"] > 0
                    and any(x["body"] == side + "_ankle_roll_link" for x in c["pair"])
                    for c in contacts
                )
                for side in ("left", "right")
            ),
            zero_step_swept_pose_no_obstacles=bool(swept_ok),
        )
        goal = (
            np.asarray(condition["start_xy_m"]) + direction * p["route_goal_distance_m"]
        ).tolist()
        conditions.append(
            {
                **condition,
                "goal_xy_m": goal,
                "initial_qpos": q0.tolist(),
                "contacts": contacts,
                "initial_guard": guard,
                "gates": gates,
                "corridor_min_radius_m": radius,
                "swept_pose_samples": 101,
                "swept_maximum_penetration_m": worst_depth,
                "forbidden_contacts": bad,
                "passed": all(gates.values()),
            }
        )
    passed = all(c["passed"] for c in conditions) and all(c["passed"] for c in coverage)
    result = {
        "schema": "native-walk-geometry-preflight/v1",
        "passed": passed,
        "physics_steps": 0,
        "dynamic_standing_qualified": False,
        "motion_authorized": False,
        "conditions": conditions,
        "coverage": coverage,
        "scene": _file_binding(root / "model/SCENE.json"),
        "plan": _file_binding(root / "PLAN.json"),
        "implementation": _file_binding(Path(__file__)),
        "scope": "zero-step geometry and contact solve only; no proof of dynamic standing or walking",
    }
    save(root / "GEOMETRY_PREFLIGHT.json", result)
    print(
        {
            "passed": passed,
            "conditions": [
                {
                    "id": c["id"],
                    "passed": c["passed"],
                    "failed": [k for k, v in c["gates"].items() if not v],
                    "corridor_radius_m": c["corridor_min_radius_m"],
                }
                for c in conditions
            ],
            "native_parts_checked": len(coverage),
            "physics_steps": 0,
        },
        flush=True,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
