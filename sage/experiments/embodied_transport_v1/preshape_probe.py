"""Finite aperture/clearance probes for a compact, empty pre-grasp hand."""

import argparse
from pathlib import Path
import numpy as np
from .kinematics import solve, ARM_NAMES
from .clearance_analysis import hand_floor
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED, group
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


def run(root):
    import mujoco

    path = root / "attempt_01/active_1000/REPORT.json"
    report = read_bound_json(path)
    trace = read_bound_json(Path(report["trace"]["path"]))
    case = read_bound_json(Path(report["case"]["path"]))
    active = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    model = mujoco.MjModel.from_xml_path(report["model"]["path"])
    data = mujoco.MjData(model)
    R = np.array(case["desired_wrist_rotation"])
    center = np.array(active[179]["substeps"][-1]["payload"]["world_position_m"])
    payload_geom = model.geom("payload_geom").id
    thumb = [
        g
        for g in range(model.ngeom)
        if model.geom_contype[g]
        and group(model.body(int(model.geom_bodyid[g])).name) == "thumb"
    ]
    fingers = [
        g
        for g in range(model.ngeom)
        if model.geom_contype[g]
        and group(model.body(int(model.geom_bodyid[g])).name) in ("index", "middle")
    ]
    results = []
    compact = []
    for fraction in (0.30, 0.45):
        data.qpos[:] = active[240]["substeps"][-1]["full_qpos_after"]
        for name, value in RIGHT_CLOSED.items():
            data.qpos[int(model.joint(name).qposadr[0])] = fraction * value
        mujoco.mj_forward(model, data)
        compact.append(
            {
                "fraction": fraction,
                "counterfactual_hand_min_z_at_saved_frame240": hand_floor(model, data),
            }
        )
        for x in (0.10, 0.115, 0.13):
            for y in (0.035, 0.05):
                data.qpos[:] = active[179]["substeps"][-1]["full_qpos_after"]
                local = np.array([x, y, 0.02])
                solution = solve(mujoco, model, data.qpos, center - R @ local, R)
                for name, value in zip(ARM_NAMES, solution["angles_rad"]):
                    data.qpos[int(model.joint(name).qposadr[0])] = value
                for name, value in RIGHT_CLOSED.items():
                    data.qpos[int(model.joint(name).qposadr[0])] = fraction * value
                mujoco.mj_forward(model, data)
                depth = max(
                    (
                        -float(c.dist)
                        for c in data.contact
                        if payload_geom in (int(c.geom1), int(c.geom2))
                    ),
                    default=0.0,
                )
                fixture = False
                for c in data.contact:
                    a, b = int(c.geom1), int(c.geom2)
                    if any(
                        model.geom(g).name.startswith("task_") for g in (a, b)
                    ) and payload_geom not in (a, b):
                        fixture = True

                def distance(geoms):
                    return min(
                        max(
                            0.0,
                            float(
                                mujoco.mj_geomDistance(
                                    model, data, payload_geom, g, 0.1, None
                                )
                            ),
                        )
                        for g in geoms
                    )

                score = distance(thumb) + distance(fingers)
                eligible = (
                    depth <= 0.002
                    and not fixture
                    and solution["position_error_m"] < 0.005
                    and solution["orientation_error_rad"] < 0.05
                )
                results.append(
                    {
                        "fraction": fraction,
                        "grasp_local_xyz_m": local.tolist(),
                        "payload_penetration_m": depth,
                        "fixture_contact": fixture,
                        "gap_score_m": score,
                        "eligible": eligible,
                        "IK": solution,
                    }
                )
    eligible = [r for r in results if r["eligible"]]
    selected = min(eligible, key=lambda r: r["gap_score_m"]) if eligible else None
    result = {
        "schema": "compact-pregrasp-geometric-probe/v1",
        "parent_report": _file_binding(path),
        "saved_state_compact_hand_clearance": compact,
        "candidates": results,
        "selected": selected,
        "physics_steps": 0,
        "scope": "12 finite empty-hand aperture checks; no dynamic grasp validation or reclassification of old failure",
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "PRESHAPE_PROBE.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
