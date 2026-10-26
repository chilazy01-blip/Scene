"""Preserved first path failed; choose a no-contact outward reference path."""

import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .kinematics_r2 import IK
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


def run(root):
    import mujoco

    case = read_bound_json(root / "CASE.json")
    case.pop("content_sha256_excluding_this_field", None)
    case["start_xy_m"][1] = 2.55
    case["source_root_goal_xy_m"][1] = 2.55
    case["target_root_goal_xy_m"][1] = 2.55
    case["initial_robot_qpos"][1] = 2.55
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    d.qpos[:50] = case["initial_robot_qpos"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], *case["source_object_quat"]]
    tested = []
    for x in np.linspace(1.15, 2.6, 30):
        d.qpos[:2] = [x, 2.55]
        mujoco.mj_forward(m, d)
        s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
        tested.append(
            {
                "kind": "root_sweep",
                "x": float(x),
                "forbidden": s["forbidden_contacts"],
                "depth": s["penetration_m"],
            }
        )
    rootbad = [r for r in tested if r["forbidden"] or r["depth"] > 0.01]
    seed = d.qpos.copy()
    seed[:2] = [1.9, 2.55]
    ik = IK(mujoco, m)
    w = m.body("right_wrist_yaw_link").id
    candidates = []
    chosen = None
    for wy, wz in ((-0.28, 0.95), (-0.32, 0.95), (-0.30, 1.0), (-0.36, 0.95)):
        d.qpos[:] = seed
        mujoco.mj_forward(m, d)
        origin = d.xpos[w].copy()
        R0 = d.xmat[w].reshape(3, 3).copy()
        grasp = np.asarray(case["source_object_xyz_m"]) - np.asarray(
            case["grasp_local_xyz_m"]
        )
        goals = [
            ("withdraw", origin + [-0.12, 0.10, 0.10], R0),
            ("orient", origin + [-0.12, 0.10, 0.10], np.eye(3)),
            ("raise", np.array([1.78, 2.55 + wy, wz]), np.eye(3)),
            ("preinsert", grasp + [-0.14, 0, 0.10], np.eye(3)),
            ("lower", grasp + [-0.14, 0, 0], np.eye(3)),
            ("insert", grasp, np.eye(3)),
        ]
        samples = []
        for phase, goal, R in goals:
            origin = d.xpos[w].copy()
            initialR = d.xmat[w].reshape(3, 3).copy()
            delta = Rotation.from_matrix(initialR.T @ R).as_rotvec()
            for f in np.linspace(0.1, 1.0, 10):
                pos = (1 - f) * origin + f * goal
                rot = initialR @ Rotation.from_rotvec(delta * f).as_matrix()
                fit = ik.solve(d.qpos, pos, rot, 100)
                d.qpos[ik.qids] = fit["angles_rad"]
                mujoco.mj_forward(m, d)
                s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
                samples.append(
                    {
                        "kind": phase,
                        "fraction": float(f),
                        "ik": fit,
                        "depth": s["penetration_m"],
                        "forbidden": s["forbidden_contacts"],
                        "bad_contacts": [
                            c
                            for c in s["contacts"]
                            if c["forbidden"] or c["distance_m"] < -0.01
                        ],
                    }
                )
        bad = [
            s
            for s in samples
            if s["forbidden"]
            or s["depth"] > 0.01
            or s["ik"]["position_error_m"] > 0.005
            or s["ik"]["orientation_error_rad"] > 0.05
        ]
        row = {
            "raise_relative_xy_z": [-0.12, wy, wz],
            "samples": samples,
            "bad": bad,
            "passed": not bad and not rootbad,
        }
        candidates.append(row)
        if row["passed"]:
            chosen = row
            break
    case["raise_relative_xy_z"] = chosen["raise_relative_xy_z"] if chosen else None
    case["stage_timeouts_ticks"]["orient"] = 200
    save(root / "CASE_R2.json", case)
    save(
        root / "TASK_GEOMETRY_PREFLIGHT_R2.json",
        {
            "schema": "native-mug-outward-arm-reference/v2",
            "passed": chosen is not None,
            "physics_steps": 0,
            "root_sweep": tested,
            "root_bad": rootbad,
            "candidates": candidates,
            "selected": chosen,
            "prior_failure": _file_binding(root / "TASK_GEOMETRY_PREFLIGHT.json"),
            "case": _file_binding(root / "CASE_R2.json"),
            "implementation": _file_binding(Path(__file__)),
            "ik_implementation": _file_binding(
                Path(__file__).with_name("kinematics_r2.py")
            ),
        },
    )
    print(
        {
            "passed": chosen is not None,
            "root_bad": rootbad[:2],
            "candidates": [
                (
                    len(r["bad"]),
                    [
                        (s["kind"], s["depth"], s["ik"]["position_error_m"])
                        for s in r["bad"][:3]
                    ],
                )
                for r in candidates
            ],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
