"""Freeze actual desk task points and zero-step whole-robot path preflight."""

import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .kinematics import IK
from .metrics import measure
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)


def run(root, parent):
    import mujoco

    p = read_bound_json(root / "GRASP_REFINED.json")
    selected = p["selected"]
    assert selected is not None
    probe = read_bound_json(root / "GRASP_PROBE.json")
    table = read_bound_json(root / "TABLE_REACH_PROBE.json")
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    d.qpos[:50] = read_bound_json(parent / "motion_cases/A.json")["initial_qpos"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 3] = probe["source_object_xyz_m"]
    yaw = selected["yaw"]
    d.qpos[adr + 3 : adr + 7] = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
    g = np.load(root / "model/MUG_GEOMETRY.npz", allow_pickle=False)["vertices"]
    lo, hi = g.min(0), g.max(0)
    corners = [
        [x, y, z]
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]
    case = {
        "schema": "native-mug-transport-case/v1",
        "start_xy_m": [1.15, 2.5],
        "start_yaw_deg": 0.0,
        "source_root_goal_xy_m": [1.9, 2.5],
        "target_root_goal_xy_m": [2.4, 2.5],
        "source_object_xyz_m": probe["source_object_xyz_m"],
        "source_object_quat": d.qpos[adr + 3 : adr + 7].tolist(),
        "target_object_xyz_m": [
            2.60,
            2.18,
            table["support"]["target"]["height"] + 0.0572,
        ],
        "support_top_m": table["support"]["source"]["height"],
        "grasp_local_xyz_m": selected["grasp_local"],
        "grip_closure": 0.30,
        "first_static_opposing_closure": selected["closure"],
        "mug_local_bounds_corners": corners,
        "initial_robot_qpos": d.qpos[:50].tolist(),
        "stage_timeouts_ticks": {
            "initial_stand": 250,
            "approach": 400,
            "source_stop": 250,
            "withdraw": 200,
            "raise": 200,
            "preinsert": 200,
            "lower": 200,
            "insert": 250,
            "close": 250,
            "lift": 250,
            "tuck": 250,
            "carry": 400,
            "target_stop": 250,
            "place": 300,
            "release": 200,
            "retract": 200,
            "settle": 250,
        },
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "not_visual_perception_autonomy": True,
    }
    ids = native._model_ids(mujoco, m)
    tested = []
    for x in np.linspace(1.15, 2.6, 30):
        d.qpos[:2] = [x, 2.5]
        mujoco.mj_forward(m, d)
        s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
        tested.append(
            {
                "kind": "root_sweep",
                "root_x": float(x),
                "forbidden": s["forbidden_contacts"],
                "depth": s["penetration_m"],
                "contacts": [c for c in s["contacts"] if c["forbidden"]],
            }
        )
    d.qpos[:2] = [1.9, 2.5]
    mujoco.mj_forward(m, d)
    ik = IK(mujoco, m)
    w = m.body("right_wrist_yaw_link").id
    origin = d.xpos[w].copy()
    R0 = d.xmat[w].reshape(3, 3).copy()
    grasp = np.asarray(case["source_object_xyz_m"]) - np.asarray(
        case["grasp_local_xyz_m"]
    )
    goals = [
        ("withdraw", origin + [-0.12, 0.08, 0.10], R0),
        ("raise", np.array([1.92, 2.38, 0.96]), np.eye(3)),
        ("preinsert", grasp + [-0.14, 0, 0.12], np.eye(3)),
        ("lower", grasp + [-0.14, 0, 0], np.eye(3)),
        ("insert", grasp, np.eye(3)),
    ]
    for phase, goal, R in goals:
        start = d.xpos[w].copy()
        initialR = d.xmat[w].reshape(3, 3).copy()
        delta = Rotation.from_matrix(initialR.T @ R).as_rotvec()
        for f in np.linspace(0.05, 1.0, 20):
            desired = (1 - f) * start + f * goal
            rot = initialR @ Rotation.from_rotvec(delta * f).as_matrix()
            result = ik.solve(d.qpos, desired, rot)
            d.qpos[ik.qids] = result["angles_rad"]
            mujoco.mj_forward(m, d)
            s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
            tested.append(
                {
                    "kind": phase,
                    "fraction": float(f),
                    "ik": result,
                    "forbidden": s["forbidden_contacts"],
                    "depth": s["penetration_m"],
                    "contacts": [c for c in s["contacts"] if c["forbidden"]],
                }
            )
    bad = [
        r
        for r in tested
        if r["forbidden"]
        or r["depth"] > 0.01
        or (
            "ik" in r
            and (
                r["ik"]["position_error_m"] > 0.005
                or r["ik"]["orientation_error_rad"] > 0.05
            )
        )
    ]
    save(
        root / "TASK_GEOMETRY_PREFLIGHT.json",
        {
            "schema": "native-mug-task-geometry/v1",
            "passed": not bad,
            "physics_steps": 0,
            "samples": tested,
            "bad": bad,
            "implementation": _file_binding(Path(__file__)),
            "not_dynamic_success": True,
        },
    )
    d.qpos[:50] = case["initial_robot_qpos"]
    d.qpos[:2] = case["start_xy_m"]
    case["initial_robot_qpos"] = d.qpos[:50].tolist()
    save(root / "CASE.json", case)
    print(
        {
            "static_path_passed": not bad,
            "bad_count": len(bad),
            "first_bad": bad[:2],
            "case": str(root / "CASE.json"),
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.parent)
