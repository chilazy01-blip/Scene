"""Bounded actual-mesh static grasp candidates; none are dynamic successes."""

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

    m = load_model(root / "model/model.xml")
    d = mujoco.MjData(m)
    d.qpos[:50] = read_bound_json(parent / "motion_cases/A.json")["initial_qpos"]
    d.qpos[:2] = [1.9, 2.5]
    reach = read_bound_json(root / "TABLE_REACH_PROBE.json")
    source = np.array([2.1, 2.18, reach["support"]["source"]["height"] + 0.0572])
    adr = m.joint("payload_free").qposadr[0]
    d.qpos[adr : adr + 3] = source
    handq = {n: m.joint(n).qposadr[0] for n in RIGHT_CLOSED}
    ik = IK(mujoco, m)
    rows = []
    for yaw in (0, math.pi / 2, math.pi, -math.pi / 2):
        for x in (0.10, 0.13, 0.15):
            for y in (0.03, 0.05, 0.07):
                local = np.array([x, y, -0.04])
                d.qpos[adr + 3 : adr + 7] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
                result = ik.solve(d.qpos, source - local, np.eye(3))
                if (
                    result["position_error_m"] > 0.005
                    or result["orientation_error_rad"] > 0.05
                ):
                    continue
                d.qpos[ik.qids] = result["angles_rad"]
                series = []
                for closure in (0, 0.2, 0.4, 0.6, 0.8):
                    for name, qid in handq.items():
                        d.qpos[qid] = closure * RIGHT_CLOSED[name]
                    mujoco.mj_forward(m, d)
                    contacts = []
                    hand_scene = []
                    for i, c in enumerate(d.contact):
                        pair = contact_pair(m, c)
                        if any(p["name"] == "payload_surface" for p in pair):
                            other = (
                                pair[1]
                                if pair[0]["name"] == "payload_surface"
                                else pair[0]
                            )
                            if other["body"].startswith("right_"):
                                contacts.append(
                                    {
                                        "group": group(other["body"]),
                                        "body": other["body"],
                                        "depth": max(0.0, -float(c.dist)),
                                    }
                                )
                        if any(
                            p["body"].startswith("right_hand_") for p in pair
                        ) and any(
                            p["name"].startswith("scene_collision_") for p in pair
                        ):
                            hand_scene.append(float(c.dist))
                    groups = set(c["group"] for c in contacts)
                    series.append(
                        {
                            "closure": closure,
                            "groups": sorted(groups),
                            "depth": max([c["depth"] for c in contacts], default=0),
                            "opposing": "thumb" in groups
                            and bool(groups & {"index", "middle"}),
                            "hand_scene_contacts": len(hand_scene),
                            "contacts": contacts,
                        }
                    )
                viable = [
                    r
                    for r in series[1:]
                    if r["opposing"]
                    and r["depth"] <= 0.004
                    and not r["hand_scene_contacts"]
                ]
                rows.append(
                    {
                        "yaw": yaw,
                        "grasp_local": local.tolist(),
                        "ik": result,
                        "series": series,
                        "viable": bool(viable) and series[0]["depth"] < 0.001,
                        "best": (
                            min(viable, key=lambda r: r["depth"]) if viable else None
                        ),
                    }
                )
    candidates = [r for r in rows if r["viable"]]
    candidates.sort(key=lambda r: r["best"]["depth"])
    save(
        root / "GRASP_PROBE.json",
        {
            "schema": "native-mug-static-grasp-probe/v1",
            "physics_steps": 0,
            "source_object_xyz_m": source.tolist(),
            "root_xy_m": [1.9, 2.5],
            "evaluated": rows,
            "candidates": candidates,
            "implementation": _file_binding(Path(__file__)),
            "not_a_dynamic_grasp_test": True,
        },
    )
    print(
        {
            "candidates": len(candidates),
            "top": [
                {k: v for k, v in r.items() if k not in ("ik", "series")}
                for r in candidates[:4]
            ],
        },
        flush=True,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--parent", type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.parent)
