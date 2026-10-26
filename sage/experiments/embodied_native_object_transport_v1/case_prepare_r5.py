"""Raise the empty hand before approaching the desk, then insert from above."""

import argparse
from pathlib import Path
import numpy as np
from .kinematics_r3 import IK
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

    case = read_bound_json(root / "CASE_R2.json")
    case.pop("content_sha256_excluding_this_field", None)
    for key in ("start_xy_m", "source_root_goal_xy_m", "target_root_goal_xy_m"):
        case[key][1] = 2.52
    for key in ("source_object_xyz_m", "target_object_xyz_m"):
        case[key][1] = 2.20
    case["initial_robot_qpos"][1] = 2.52
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    ik = IK(mujoco, m)
    d.qpos[:50] = case["initial_robot_qpos"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], *case["source_object_quat"]]
    seed = d.qpos.copy()
    mujoco.mj_forward(m, d)
    w = m.body("right_wrist_yaw_link").id
    grasp = np.asarray(case["source_object_xyz_m"]) - np.asarray(
        case["grasp_local_xyz_m"]
    )
    candidates = []
    chosen = None
    for relative in ((0.12, -0.36, 0.18), (0.16, -0.36, 0.20), (0.08, -0.38, 0.18)):
        d.qpos[:] = seed
        goal = d.qpos[:3] + np.asarray(relative)
        result = ik.solve(d.qpos, goal, np.eye(3), 150)
        initial = d.qpos[ik.qids].copy()
        samples = []
        for f in np.linspace(0, 1, 21):
            d.qpos[ik.qids] = (1 - f) * initial + f * np.asarray(result["angles_rad"])
            mujoco.mj_forward(m, d)
            s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
            samples.append(
                {
                    "phase": "ready_arm",
                    "depth": s["penetration_m"],
                    "forbidden": s["forbidden_contacts"],
                }
            )
        for x in np.linspace(1.15, 2.6, 30):
            d.qpos[:2] = [x, 2.52]
            mujoco.mj_forward(m, d)
            s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
            samples.append(
                {
                    "phase": "ready_arm_walk",
                    "depth": s["penetration_m"],
                    "forbidden": s["forbidden_contacts"],
                }
            )
        d.qpos[:2] = [1.9, 2.52]
        mujoco.mj_forward(m, d)
        waypoints = []
        for phase, pos in (
            ("preinsert", grasp + [-0.10, 0, 0.10]),
            ("lower", grasp + [-0.10, 0, 0]),
            ("insert", grasp),
        ):
            origin = d.xpos[w].copy()
            for f in np.linspace(0.05, 1, 20):
                fit = ik.solve(d.qpos, (1 - f) * origin + f * pos, np.eye(3), 150)
                d.qpos[ik.qids] = fit["angles_rad"]
                mujoco.mj_forward(m, d)
                s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
                samples.append(
                    {
                        "phase": phase,
                        "depth": s["penetration_m"],
                        "forbidden": s["forbidden_contacts"],
                        "ik_error": fit["position_error_m"],
                        "angle_error": fit["orientation_error_rad"],
                    }
                )
            waypoints.append(
                {
                    "phase": phase,
                    "goal": pos.tolist(),
                    "angles": d.qpos[ik.qids].tolist(),
                }
            )
        bad = [
            s
            for s in samples
            if s["forbidden"]
            or s["depth"] > 0.01
            or s.get("ik_error", 0) > 0.005
            or s.get("angle_error", 0) > 0.05
        ]
        row = {
            "relative": list(relative),
            "ik": result,
            "samples": samples,
            "bad": bad,
            "passed": not bad
            and result["position_error_m"] < 0.005
            and result["orientation_error_rad"] < 0.05,
            "waypoints": waypoints,
        }
        candidates.append(row)
        if row["passed"]:
            chosen = row
            break
    case["ready_arm_relative_m"] = chosen["relative"] if chosen else None
    case["ready_arm_target_rad"] = chosen["ik"]["angles_rad"] if chosen else None
    case["insertion_retreat_m"] = 0.10
    case["stage_timeouts_ticks"]["ready_arm"] = 200
    save(root / "CASE_R5.json", case)
    save(
        root / "TASK_GEOMETRY_PREFLIGHT_R5.json",
        {
            "schema": "native-mug-ready-before-walk/v5",
            "passed": chosen is not None,
            "physics_steps": 0,
            "candidates": candidates,
            "selected": chosen,
            "prior": _file_binding(root / "TASK_GEOMETRY_PREFLIGHT_R4.json"),
            "case": _file_binding(root / "CASE_R5.json"),
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "passed": chosen is not None,
            "candidates": [
                {
                    "relative": r["relative"],
                    "ik_error": r["ik"]["position_error_m"],
                    "bad": len(r["bad"]),
                    "first_bad": r["bad"][:3],
                }
                for r in candidates
            ],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
