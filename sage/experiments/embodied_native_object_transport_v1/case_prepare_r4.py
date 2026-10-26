"""Joint-reference path around native desk, all prior geometry failures retained."""

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
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    d.qpos[:50] = case["initial_robot_qpos"]
    d.qpos[:2] = [1.9, 2.55]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], *case["source_object_quat"]]
    seed = d.qpos.copy()
    ik = IK(mujoco, m)
    grasp = np.asarray(case["source_object_xyz_m"]) - np.asarray(
        case["grasp_local_xyz_m"]
    )
    outcomes = []
    chosen = None
    for retreat in (0.10, 0.08, 0.06):
        d.qpos[:] = seed
        goals = [
            ("raise", np.array([1.93, 2.27, 0.95])),
            ("preinsert", grasp + [-retreat, 0, 0.10]),
            ("lower", grasp + [-retreat, 0, 0]),
            ("insert", grasp),
        ]
        samples = []
        targets = []
        for phase, goal in goals:
            result = ik.solve(d.qpos, goal, np.eye(3), 150)
            initial = d.qpos[ik.qids].copy()
            targets.append({"phase": phase, "goal": goal.tolist(), "ik": result})
            for f in np.linspace(0, 1, 21):
                d.qpos[ik.qids] = (1 - f) * initial + f * np.asarray(
                    result["angles_rad"]
                )
                mujoco.mj_forward(m, d)
                s = measure(mujoco, m, d, ids, np.zeros(m.nv), case)
                samples.append(
                    {
                        "phase": phase,
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
        bad = [s for s in samples if s["forbidden"] or s["depth"] > 0.01]
        row = {
            "retreat_m": retreat,
            "targets": targets,
            "samples": samples,
            "bad": bad,
            "passed": not bad
            and all(
                t["ik"]["position_error_m"] < 0.005
                and t["ik"]["orientation_error_rad"] < 0.05
                for t in targets
            ),
        }
        outcomes.append(row)
        if row["passed"]:
            chosen = row
            break
    case["joint_reach_waypoints"] = chosen["targets"] if chosen else None
    case["insertion_retreat_m"] = chosen["retreat_m"] if chosen else None
    save(root / "CASE_R4.json", case)
    save(
        root / "TASK_GEOMETRY_PREFLIGHT_R4.json",
        {
            "schema": "native-mug-safe-joint-path/v4",
            "passed": chosen is not None,
            "physics_steps": 0,
            "candidates": outcomes,
            "selected": chosen,
            "prior": _file_binding(root / "TASK_GEOMETRY_PREFLIGHT_R3.json"),
            "case": _file_binding(root / "CASE_R4.json"),
            "implementation": _file_binding(Path(__file__)),
            "ik": _file_binding(Path(__file__).with_name("kinematics_r3.py")),
        },
    )
    print(
        {
            "passed": chosen is not None,
            "outcomes": [
                {
                    "retreat": r["retreat_m"],
                    "bad": len(r["bad"]),
                    "errors": [
                        (t["phase"], t["ik"]["position_error_m"]) for t in r["targets"]
                    ],
                    "first_bad": [
                        (s["phase"], s["depth"], s["forbidden"]) for s in r["bad"][:2]
                    ],
                }
                for r in outcomes
            ],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    run(ap.parse_args().root)
