"""Finite safe-corridor IK alternatives, before any H2 physical execution."""

import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .prepare import save
from sage.experiments.embodied_transport_v1.kinematics import solve, ARM_NAMES
from sage.experiments.embodied_transport_v1.metrics_r5 import observe
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    case = read_bound_json(root / "CASE.json")
    parent = (
        root.parent
        / "embodied_transport_hybrid_20261020_v1/attempt_01/active_0500/REPORT.json"
    )
    report = read_bound_json(parent)
    trace = read_bound_json(Path(report["trace"]["path"]))
    rows = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    m = mujoco.MjModel.from_xml_path(case["model_path"])
    w = m.body("right_wrist_yaw_link").id
    original = np.array(rows[49]["substeps"][-1]["full_qpos_after"])
    results = []
    for waypoint in (
        [1.20, 2.50, 1.02],
        [1.22, 2.48, 1.02],
        [1.24, 2.46, 1.04],
        [1.20, 2.46, 1.00],
    ):
        d = mujoco.MjData(m)
        d.qpos[:] = original
        for name, value in RIGHT_CLOSED.items():
            d.qpos[int(m.joint(name).qposadr[0])] = value * case["ready_fraction"]
        mujoco.mj_forward(m, d)
        origin = d.xpos[w].copy()
        R = d.xmat[w].reshape(3, 3).copy()
        grasp = np.array(case["source_object_xyz_m"]) - np.array(
            case["grasp_local_xyz_m"]
        )
        place = np.array(case["target_object_xyz_m"]) - np.array(
            case["grasp_local_xyz_m"]
        )
        segments = [
            ("withdraw", origin + [-0.16, 0.06, 0.15], R),
            ("orient", origin + [-0.16, 0.06, 0.15], np.eye(3)),
            ("raise_clear", np.array(waypoint), np.eye(3)),
            ("overhead", grasp + [0, 0, 0.18], np.eye(3)),
            ("descend", grasp, np.eye(3)),
            ("lift", grasp + [0, 0, 0.08], np.eye(3)),
            ("place", place, np.eye(3)),
        ]
        checks = []
        for phase, goal, target_R in segments:
            start = d.xpos[w].copy()
            start_R = d.xmat[w].reshape(3, 3).copy()
            delta = Rotation.from_matrix(start_R.T @ target_R).as_rotvec()
            for i in range(1, 21):
                f = i / 20
                s = solve(
                    mujoco,
                    m,
                    d.qpos,
                    start * (1 - f) + goal * f,
                    start_R @ Rotation.from_rotvec(delta * f).as_matrix(),
                    max_evaluations=200,
                )
                for name, value in zip(ARM_NAMES, s["angles_rad"]):
                    d.qpos[int(m.joint(name).qposadr[0])] = value
                mujoco.mj_forward(m, d)
                p = observe(mujoco, m, d)
                penetration = max(
                    (
                        -c["distance_m"]
                        for c in p["contacts"]
                        if c["role"] in ("thumb", "index", "middle", "palm")
                    ),
                    default=0.0,
                )
                checks.append(
                    {
                        "phase": phase,
                        "sample": i,
                        "pos": s["position_error_m"],
                        "rot": s["orientation_error_rad"],
                        "joint_margin": s["joint_limit_margin_rad"],
                        "fixture": p["body_fixture_violation"],
                        "scene": p["scene_violation"],
                        "payload_penetration_m": penetration,
                        "contact_gate_applicable": phase not in ("lift", "place"),
                    }
                )
        passed = all(
            c["pos"] < 0.005
            and c["rot"] < 0.05
            and not c["fixture"]
            and not c["scene"]
            and (
                not c["contact_gate_applicable"] or c["payload_penetration_m"] < 0.0005
            )
            for c in checks
        )
        results.append({"waypoint": waypoint, "passed": passed, "samples": checks})
        print(
            {
                "waypoint": waypoint,
                "passed": passed,
                "max_pos": max(c["pos"] for c in checks),
                "max_rot": max(c["rot"] for c in checks),
                "max_pregrasp_penetration": max(
                    c["payload_penetration_m"]
                    for c in checks
                    if c["contact_gate_applicable"]
                ),
            },
            flush=True,
        )
    selected = next((r for r in results if r["passed"]), None)
    save(
        root / "PREFLIGHT_SAFE.json",
        {
            "passed": selected is not None,
            "selected_waypoint": selected["waypoint"] if selected else None,
            "candidates": results,
            "physics_steps": 0,
            "case": _file_binding(root / "CASE.json"),
            "model": _file_binding(Path(case["model_path"])),
            "parent_report": _file_binding(parent),
            "implementation": _file_binding(Path(__file__)),
            "scope": "reference swept mesh checks; only before grasp uses static source-object contact gate, because payload would move with hand after pickup; not physical success",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
