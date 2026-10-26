"""Resolve first touch for the already bounded open-safe mesh candidates."""

import argparse
from pathlib import Path
import math
import numpy as np
from .kinematics import IK
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_native_v1.contacts import contact_pair
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED, group
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root, parent):
    import mujoco

    p = read_bound_json(root / "GRASP_PROBE.json")
    candidates = [r for r in p["evaluated"] if r["series"][0]["depth"] < 0.001]
    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    d.qpos[:50] = read_bound_json(parent / "motion_cases/A.json")["initial_qpos"]
    d.qpos[:2] = p["root_xy_m"]
    adr = int(m.joint("payload_free").qposadr[0])
    d.qpos[adr : adr + 3] = p["source_object_xyz_m"]
    handq = {n: m.joint(n).qposadr[0] for n in RIGHT_CLOSED}
    rows = []
    for r in candidates:
        d.qpos[adr + 3 : adr + 7] = [
            math.cos(r["yaw"] / 2),
            0,
            0,
            math.sin(r["yaw"] / 2),
        ]
        from .kinematics import ARM_NAMES

        qids = [m.joint(n).qposadr[0] for n in ARM_NAMES]
        d.qpos[qids] = r["ik"]["angles_rad"]
        for closure in (0.025, 0.05, 0.075, 0.10, 0.125, 0.15, 0.175):
            for name, qid in handq.items():
                d.qpos[qid] = closure * RIGHT_CLOSED[name]
            mujoco.mj_forward(m, d)
            groups = set()
            depth = 0
            for c in d.contact:
                pair = contact_pair(m, c)
                if not any(s["name"] == "payload_surface" for s in pair):
                    continue
                other = pair[1] if pair[0]["name"] == "payload_surface" else pair[0]
                if other["body"].startswith("right_"):
                    groups.add(group(other["body"]))
                    depth = max(depth, -float(c.dist))
            rows.append(
                {
                    "yaw": r["yaw"],
                    "grasp_local": r["grasp_local"],
                    "closure": closure,
                    "groups": sorted(groups),
                    "depth": depth,
                    "opposing": "thumb" in groups
                    and bool(groups & {"index", "middle"}),
                    "ik": r["ik"],
                }
            )
    viable = [r for r in rows if r["opposing"] and r["depth"] <= 0.004]
    viable.sort(key=lambda r: r["depth"])
    selected = viable[0] if viable else None
    save(
        root / "GRASP_REFINED.json",
        {
            "schema": "native-mug-first-touch-probe/v1",
            "physics_steps": 0,
            "parent": _file_binding(root / "GRASP_PROBE.json"),
            "evaluated": rows,
            "selected": selected,
            "implementation": _file_binding(Path(__file__)),
            "target_closure_geometry_not_actual_finger_penetration": True,
        },
    )
    print({"selected": selected, "open_safe_candidates": len(candidates)}, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.parent)
