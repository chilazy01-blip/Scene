"""Joint-space initial lift avoids a singular fixed-orientation withdrawal."""

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

    case = read_bound_json(root / "CASE_R2.json")
    case.pop("content_sha256_excluding_this_field", None)
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    d.qpos[:50] = case["initial_robot_qpos"]
    d.qpos[:2] = [1.9, 2.55]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], *case["source_object_quat"]]
    mujoco.mj_forward(m, d)
    seed = d.qpos.copy()
    ik = IK(mujoco, m)
    w = m.body("right_wrist_yaw_link").id
    good = read_bound_json(root / "GRASP_REFINED.json")["selected"]["ik"]["angles_rad"]
    grasp = np.asarray(case["source_object_xyz_m"]) - np.asarray(
        case["grasp_local_xyz_m"]
    )
    results = []
    chosen = None
    for relative in (
        (-0.08, -0.26, 0.92),
        (-0.12, -0.32, 0.92),
        (-0.10, -0.35, 1.0),
        (0.03, -0.28, 0.95),
    ):
        goal = np.array([1.9 + relative[0], 2.55 + relative[1], relative[2]])
        ikseed = seed.copy()
        ikseed[ik.qids] = good
        target = ik.solve(ikseed, goal, np.eye(3), 150)
        d.qpos[:] = seed
        initial = seed[ik.qids].copy()
        samples = []
        for f in np.linspace(0, 1, 21):
            d.qpos[ik.qids] = (1 - f) * initial + f * np.asarray(target["angles_rad"])
            mujoco.mj_forward(m, d)
            s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
            samples.append(
                {
                    "phase": "joint_raise",
                    "fraction": float(f),
                    "depth": s["penetration_m"],
                    "forbidden": s["forbidden_contacts"],
                    "bad_contacts": [
                        c
                        for c in s["contacts"]
                        if c["forbidden"] or c["distance_m"] < -0.01
                    ],
                }
            )
        for phase, pos in (
            ("preinsert", grasp + [-0.14, 0, 0.10]),
            ("lower", grasp + [-0.14, 0, 0]),
            ("insert", grasp),
        ):
            origin = d.xpos[w].copy()
            for f in np.linspace(0.05, 1, 20):
                fit = ik.solve(d.qpos, (1 - f) * origin + f * pos, np.eye(3), 100)
                d.qpos[ik.qids] = fit["angles_rad"]
                mujoco.mj_forward(m, d)
                s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
                samples.append(
                    {
                        "phase": phase,
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
            r
            for r in samples
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
        row = {
            "relative": list(relative),
            "target_ik": target,
            "samples": samples,
            "bad": bad,
            "passed": not bad
            and target["position_error_m"] < 0.005
            and target["orientation_error_rad"] < 0.05,
        }
        results.append(row)
        if row["passed"]:
            chosen = row
            break
    assert not read_bound_json(root / "TASK_GEOMETRY_PREFLIGHT_R2.json")["root_bad"]
    case["raise_joint_target_rad"] = (
        chosen["target_ik"]["angles_rad"] if chosen else None
    )
    case["raise_goal_m"] = (
        [
            1.9 + chosen["relative"][0],
            2.55 + chosen["relative"][1],
            chosen["relative"][2],
        ]
        if chosen
        else None
    )
    save(root / "CASE_R3.json", case)
    save(
        root / "TASK_GEOMETRY_PREFLIGHT_R3.json",
        {
            "schema": "native-mug-joint-raise-preflight/v3",
            "passed": chosen is not None,
            "physics_steps": 0,
            "candidates": results,
            "selected": chosen,
            "case": _file_binding(root / "CASE_R3.json"),
            "prior": _file_binding(root / "TASK_GEOMETRY_PREFLIGHT_R2.json"),
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "passed": chosen is not None,
            "candidates": [
                (
                    r["relative"],
                    len(r["bad"]),
                    [(s["phase"], s["depth"]) for s in r["bad"][:3]],
                )
                for r in results
            ],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
