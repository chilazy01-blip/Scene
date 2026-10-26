"""Audit the purpose of an intermediate waypoint using real hand mesh clearance."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def hand_floor(model, data):
    minimum = float("inf")
    for g in range(model.ngeom):
        name = model.body(int(model.geom_bodyid[g])).name
        if not model.geom_contype[g] or not (
            name.startswith("right_hand_") or name == "right_wrist_yaw_link"
        ):
            continue
        mesh = int(model.geom_dataid[g])
        if mesh >= 0 and int(model.geom_type[g]) == 7:
            start = int(model.mesh_vertadr[mesh])
            count = int(model.mesh_vertnum[mesh])
            verts = model.mesh_vert[start : start + count]
            bottom = float(
                data.geom_xpos[g, 2]
                + np.min(verts @ data.geom_xmat[g].reshape(3, 3)[2])
            )
        else:
            bottom = float(data.geom_xpos[g, 2] - model.geom_rbound[g])
        minimum = min(minimum, bottom)
    return minimum


def run(root):
    import mujoco

    path = root / "attempt_01/active_1000/REPORT.json"
    report = read_bound_json(path)
    trace = read_bound_json(Path(report["trace"]["path"]))
    model = mujoco.MjModel.from_xml_path(report["model"]["path"])
    data = mujoco.MjData(model)
    wrist = model.body("right_wrist_yaw_link").id
    payload = model.body("payload").id
    geom = model.geom("payload_geom").id
    count = 0
    first = None
    sampled = []
    for row in trace["records"]:
        if (
            not row["sonic_candidate_consumed_by_physics"]
            or row["task"].get("reach_subphase") != "clear_vertical"
            or row["reference_tick"] < 240
        ):
            continue
        data.qpos[:] = row["substeps"][-1]["full_qpos_after"]
        mujoco.mj_forward(model, data)
        axis = data.xmat[payload].reshape(3, 3)[:, 2]
        extent = model.geom_size[geom, 1] * abs(axis[2]) + model.geom_size[
            geom, 0
        ] * np.linalg.norm(axis[:2])
        top = float(data.xpos[payload, 2] + extent)
        bottom = hand_floor(model, data)
        goal = np.array(row["task"]["sub_goal_m"])
        xy = float(np.linalg.norm(data.xpos[wrist, :2] - goal[:2]))
        clearance = bottom - top
        ready = clearance >= 0.012 and xy <= 0.05
        count = count + 1 if ready else 0
        record = {
            "frame": row["reference_tick"],
            "hand_min_z_m": bottom,
            "object_max_z_m": top,
            "clearance_m": clearance,
            "wrist_xy_error_m": xy,
            "original_xyz_error_m": float(np.linalg.norm(data.xpos[wrist] - goal)),
            "consecutive_clear_ticks": count,
        }
        if count >= 5 and first is None:
            first = record
        if row["reference_tick"] % 10 == 0:
            sampled.append(record)
    result = {
        "schema": "intermediate-waypoint-clearance-review/v1",
        "parent_report": _file_binding(path),
        "first_5_tick_clearance_gate": first,
        "sampled": sampled,
        "physics_steps": 0,
        "scope": "saved-state purpose-specific clearance gate only, not evidence of a changed physical rollout or successful grasp",
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "CLEARANCE_REVIEW.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
