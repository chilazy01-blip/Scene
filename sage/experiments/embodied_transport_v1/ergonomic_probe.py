"""Finite alternative task-interface certificate after the first batch exit."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET
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
    active = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    xml = ET.parse(report["model"]["path"]).getroot()
    for node in xml.findall("asset/*"):
        if node.get("file"):
            node.set(
                "file", str(Path(report["model"]["path"]).parent / node.get("file"))
            )
    xml.find(".//geom[@name='payload_geom']").set("size", ".02 .06")
    for name, radius in (("source", 0.015), ("target", 0.05)):
        support = xml.find(f".//geom[@name='task_{name}_support']")
        support.set("size", f"{radius} .005")
        support.set("pos", "0 0 .795")
    model = mujoco.MjModel.from_xml_string(ET.tostring(xml, encoding="unicode"))
    data = mujoco.MjData(model)
    original = np.array(active[179]["substeps"][-1]["full_qpos_after"])
    adr = int(model.joint("payload_free").qposadr[0])
    object_geom = model.geom("payload_geom").id
    center = np.array([1.45, 2.45, 0.86])
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
    for fraction in (0.3, 0.45):
        for local in (np.array([0.115, 0.04, -0.01]), np.array([0.13, 0.05, -0.01])):
            data.qpos[:] = original
            data.qpos[adr : adr + 7] = [*center, 1, 0, 0, 0]
            wrist = center - local
            solution = solve(mujoco, model, data.qpos, wrist, np.eye(3))
            for name, value in zip(ARM_NAMES, solution["angles_rad"]):
                data.qpos[int(model.joint(name).qposadr[0])] = value
            for name, value in RIGHT_CLOSED.items():
                data.qpos[int(model.joint(name).qposadr[0])] = fraction * value
            mujoco.mj_forward(model, data)
            penetration = max(
                (
                    -float(c.dist)
                    for c in data.contact
                    if object_geom in (int(c.geom1), int(c.geom2))
                ),
                default=0.0,
            )
            fixture = any(
                any(
                    model.geom(int(g)).name.startswith("task_")
                    for g in (c.geom1, c.geom2)
                )
                and object_geom not in (int(c.geom1), int(c.geom2))
                for c in data.contact
            )
            score = sum(
                min(
                    max(
                        0.0,
                        float(
                            mujoco.mj_geomDistance(
                                model, data, object_geom, g, 0.1, None
                            )
                        ),
                    )
                    for g in geoms
                )
                for geoms in (thumb, fingers)
            )
            insertion = solve(
                mujoco, model, original, wrist - np.array([0.08, 0, 0]), np.eye(3)
            )
            eligible = (
                not fixture
                and penetration <= 0.002
                and solution["position_error_m"] < 0.005
                and solution["orientation_error_rad"] < 0.05
                and insertion["position_error_m"] < 0.005
            )
            results.append(
                {
                    "fraction": fraction,
                    "grasp_local_xyz_m": local.tolist(),
                    "desired_wrist_m": wrist.tolist(),
                    "hand_bottom_above_support_m": hand_floor(model, data) - 0.8,
                    "payload_penetration_m": penetration,
                    "fixture_contact": fixture,
                    "gap_score_m": score,
                    "IK": solution,
                    "preinsert_IK": insertion,
                    "eligible": bool(eligible),
                }
            )
    eligible = [r for r in results if r["eligible"]]
    selected = min(eligible, key=lambda r: r["gap_score_m"]) if eligible else None
    result = {
        "schema": "ergonomic-side-grasp-interface/v1",
        "parent_report": _file_binding(path),
        "profile": {
            "support_top_m": 0.8,
            "object_center_m": center.tolist(),
            "payload_radius_m": 0.02,
            "payload_half_height_m": 0.06,
            "payload_mass_kg": 0.05,
            "desired_wrist_rotation": np.eye(3).tolist(),
            "fixture_geometry": "thin15mm shaft and explicit target50mm top plate; no robot-support contacts allowed",
        },
        "candidates": results,
        "selected": selected,
        "physics_steps": 0,
        "first_batch_exit": "all4 causal task-interface/motion revisions ended without physical pickup; no further physics on those protocols",
        "scope": "four finite aperture/IK checks for a new ergonomic task profile, not a physical grasp claim",
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "ERGONOMIC_PROBE.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
