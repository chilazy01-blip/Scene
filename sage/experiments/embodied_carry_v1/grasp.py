"""Bounded zero-step contact placement with exact hand meshes, behind gate."""

import argparse
from pathlib import Path
import numpy as np

from .model import authorize
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
)

RIGHT_CLOSED = {
    "right_hand_thumb_0_joint": 0.8,
    "right_hand_thumb_1_joint": -0.9,
    "right_hand_thumb_2_joint": -1.5,
    "right_hand_index_0_joint": 1.4,
    "right_hand_index_1_joint": 1.5,
    "right_hand_middle_0_joint": 1.4,
    "right_hand_middle_1_joint": 1.5,
}


def group(name):
    if name.startswith("right_hand_thumb"):
        return "thumb"
    if name.startswith("right_hand_index"):
        return "index"
    if name.startswith("right_hand_middle"):
        return "middle"
    if name == "right_wrist_yaw_link":
        return "palm"
    return "other"


def payload_metrics(mujoco, model, data, initial_local=None):
    bid = model.body("payload").id
    gid = model.geom("payload_geom").id
    wrist = model.body("right_wrist_yaw_link").id
    local = data.xmat[wrist].reshape(3, 3).T @ (data.xpos[bid] - data.xpos[wrist])
    groups = set()
    contacts = []
    bad = False
    for i, c in enumerate(data.contact):
        a, b = int(c.geom1), int(c.geom2)
        if gid not in (a, b):
            continue
        other = b if a == gid else a
        name = model.body(int(model.geom_bodyid[other])).name
        label = group(name)
        bad |= label == "other"
        force = np.zeros(6)
        mujoco.mj_contactForce(model, data, i, force)
        if force[0] > 0.01:
            groups.add(label)
        contacts.append(
            {
                "body": name,
                "group": label,
                "normal_force_n": float(force[0]),
                "distance_m": float(c.dist),
            }
        )
    opposing = "thumb" in groups and bool({"index", "middle"} & groups)
    slip = (
        float(np.linalg.norm(local - initial_local))
        if initial_local is not None
        else 0.0
    )
    return {
        "world_position_m": data.xpos[bid].tolist(),
        "local_position_m": local.tolist(),
        "contacts": contacts,
        "opposing_finger_contact": opposing,
        "non_hand_contact": bool(bad),
        "relative_position_error_m": slip,
        "height_m": float(data.xpos[bid, 2]),
        "held": bool(
            opposing and not bad and slip <= 0.03 and data.xpos[bid, 2] >= 0.25
        ),
    }


def search(main_root, model_root, output):
    import mujoco

    authorize(main_root)
    if output.exists():
        raise FileExistsError(output)
    description = read_bound_json(model_root / "SCENE.json")
    model = mujoco.MjModel.from_xml_path(str(model_root / "model.xml"))
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    data.qpos[ids["qpos_ids"]] = DEFAULT_ANGLES
    data.qpos[:2] = [0.85, 2.8]
    object_adr = int(model.joint("payload_free").qposadr[0])
    object_geom = model.geom("payload_geom").id
    wrist = model.body("right_wrist_yaw_link").id
    thumb = [
        i
        for i in range(model.ngeom)
        if model.geom_contype[i]
        and group(model.body(int(model.geom_bodyid[i])).name) == "thumb"
    ]
    other = [
        i
        for i in range(model.ngeom)
        if model.geom_contype[i]
        and group(model.body(int(model.geom_bodyid[i])).name) in ("index", "middle")
    ]
    results = []
    evaluations = 0
    for closure in (0.45, 0.60, 0.75):
        initial = {n: closure * v for n, v in RIGHT_CLOSED.items()}
        for name, value in initial.items():
            data.qpos[int(model.joint(name).qposadr[0])] = value
        mujoco.mj_forward(model, data)
        rotation = data.xmat[wrist].reshape(3, 3).copy()
        origin = data.xpos[wrist].copy()
        quaternion = data.xquat[wrist].copy()
        scored = []
        for x in np.arange(0.09, 0.161, 0.01):
            for y in np.arange(0, 0.061, 0.01):
                for z in (-0.02, 0.0, 0.02):
                    local = np.array([x, y, z])
                    data.qpos[object_adr : object_adr + 3] = origin + rotation @ local
                    data.qpos[object_adr + 3 : object_adr + 7] = quaternion
                    mujoco.mj_forward(model, data)
                    evaluations += 1
                    contacts = [
                        c
                        for c in data.contact
                        if object_geom in (int(c.geom1), int(c.geom2))
                    ]
                    penetration = max((-float(c.dist) for c in contacts), default=0.0)
                    if penetration > 0.002 or any(c.dist < -0.01 for c in data.contact):
                        continue
                    if any(
                        group(
                            model.body(
                                int(
                                    model.geom_bodyid[
                                        (
                                            int(c.geom2)
                                            if int(c.geom1) == object_geom
                                            else int(c.geom1)
                                        )
                                    ]
                                )
                            ).name
                        )
                        == "other"
                        for c in contacts
                    ):
                        continue

                    def distance(geoms):
                        values = []
                        for g in geoms:
                            actual = [
                                float(c.dist)
                                for c in contacts
                                if g in (int(c.geom1), int(c.geom2))
                            ]
                            values.append(
                                min(actual)
                                if actual
                                else max(
                                    0.0,
                                    mujoco.mj_geomDistance(
                                        model, data, object_geom, g, 0.1, None
                                    ),
                                )
                            )
                        return min(values, default=0.1)

                    gap_thumb = distance(thumb)
                    gap_other = distance(other)
                    score = max(gap_thumb, 0) + max(gap_other, 0) + penetration * 4
                    scored.append(
                        {
                            "closure": closure,
                            "payload_local_xyz_m": local.tolist(),
                            "initial_right_hand_targets": initial,
                            "right_hand_targets": RIGHT_CLOSED,
                            "static_payload_penetration_m": penetration,
                            "thumb_gap_m": gap_thumb,
                            "other_finger_gap_m": gap_other,
                            "score": score,
                        }
                    )
        if scored:
            results.append(min(scored, key=lambda r: r["score"]))
    results.sort(key=lambda r: r["score"])
    document = {
        "schema": "carry-grasp-geometric-preflight/v1",
        "candidates": results,
        "evaluations": evaluations,
        "model": _file_binding(model_root / "SCENE.json"),
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
        "grasp_validated": False,
        "note": "bounded preloaded placement, no object attachment; static distances are diagnostics, dynamic retention must pass separately",
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(output, document)
    print(
        "grasp preflight",
        evaluations,
        "static placements",
        len(results),
        "candidate closures",
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--main-root", type=Path, required=True)
    p.add_argument("--model-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    search(a.main_root, a.model_root, a.output)
