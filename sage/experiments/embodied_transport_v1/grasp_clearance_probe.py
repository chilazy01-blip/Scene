"""Saved-state open-hand clearance probes for top-access grasp geometry."""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from .kinematics import solve, ARM_NAMES
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

    report = read_bound_json(root / "attempt_01/active_0300/REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    case = read_bound_json(Path(report["case"]["path"]))
    state = next(r for r in trace["records"] if r["reference_tick"] == 179)["substeps"][
        -1
    ]
    R = np.array(case["desired_wrist_rotation"])
    grasp = np.array(case["grasp_local_xyz_m"])
    relR = np.array(case["grasp_local_rotation"])
    outcomes = []
    for half_height, offset in ((0.04, 0.0), (0.06, 0.03)):
        xml = ET.parse(report["model"]["path"]).getroot()
        for node in xml.findall("asset/*"):
            if node.get("file"):
                node.set(
                    "file", str(Path(report["model"]["path"]).parent / node.get("file"))
                )
        xml.find(".//geom[@name='payload_geom']").set("size", f".02 {half_height}")
        model = mujoco.MjModel.from_xml_string(ET.tostring(xml, encoding="unicode"))
        data = mujoco.MjData(model)
        data.qpos[:] = state["full_qpos_after"]
        adr = int(model.joint("payload_free").qposadr[0])
        center = np.array([1.45, 2.45, 0.65 + half_height])
        data.qpos[adr : adr + 7] = [*center, 1, 0, 0, 0]
        local = grasp - relR[:, 2] * offset
        wrist = center - R @ local
        result = solve(mujoco, model, data.qpos, wrist, R)
        for name, value in zip(ARM_NAMES, result["angles_rad"]):
            data.qpos[int(model.joint(name).qposadr[0])] = value
        for i in range(model.njnt):
            if model.joint(i).name.startswith("right_hand_"):
                data.qpos[int(model.joint(i).qposadr[0])] = 0
        mujoco.mj_forward(model, data)
        contacts = []
        for c in data.contact:
            a, b = int(c.geom1), int(c.geom2)
            names = [model.geom(g).name for g in (a, b)]
            if any(n.startswith("task_") for n in names):
                contacts.append(
                    {
                        "geoms": names,
                        "bodies": [
                            model.body(int(model.geom_bodyid[g])).name for g in (a, b)
                        ],
                        "distance_m": float(c.dist),
                    }
                )
        outcomes.append(
            {
                "half_height_m": half_height,
                "grip_above_com_m": offset,
                "center_m": center.tolist(),
                "grasp_local_xyz_m": local.tolist(),
                "desired_wrist_m": wrist.tolist(),
                "IK": result,
                "support_contacts_at_open_grasp": contacts,
            }
        )
    result = {
        "schema": "open-grasp-support-clearance/v1",
        "parent_rejection": _file_binding(root / "attempt_01/active_0300/REPORT.json"),
        "observed_failure": "open palm touched source post during lateral orientation change, before grasp closure; <=1mm penetration but correctly rejected as fixture support",
        "profiles": outcomes,
        "proposed_motion": "align orientation above the source, then lower; taller12cm cylinder grasped3cm above COM keeps palm clear of source fixture",
        "physics_steps": 0,
        "implementation": _file_binding(Path(__file__)),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(root / "GRASP_CLEARANCE_PROBE.json", result)
    print(result)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
