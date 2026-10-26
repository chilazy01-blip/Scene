"""Zero-step native tabletop ray heights and arm reach, before placing task points."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_contact_v1.fast_kinematics import solve
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def top_height(triangles, xy):
    a, b, c = triangles.transpose(1, 0, 2)
    u, v = b[:, :2] - a[:, :2], c[:, :2] - a[:, :2]
    d = np.asarray(xy) - a[:, :2]
    den = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    good = np.abs(den) > 1e-12
    s = np.zeros(len(den))
    t = s.copy()
    s[good] = (d[good, 0] * v[good, 1] - d[good, 1] * v[good, 0]) / den[good]
    t[good] = (u[good, 0] * d[good, 1] - u[good, 1] * d[good, 0]) / den[good]
    hit = good & (s >= -1e-9) & (t >= -1e-9) & (s + t <= 1 + 1e-9)
    if not np.any(hit):
        return None
    heights = a[:, 2] + s * (b[:, 2] - a[:, 2]) + t * (c[:, 2] - a[:, 2])
    return float(max(heights[hit]))


def run(root, parent):
    import trimesh
    import mujoco

    scene = read_bound_json(parent / "model/SCENE.json")
    model = load_model(scene["model"]["path"])
    data = mujoco.MjData(model)
    seed = np.asarray(read_bound_json(parent / "motion_cases/A.json")["initial_qpos"])
    data.qpos[:] = seed
    mujoco.mj_kinematics(model, data)
    desk = next(
        s for s in scene["native_collision_surfaces"] if s["body"] == "generated_desk"
    )
    mesh = trimesh.load(desk["source"]["path"], force="mesh", process=False)
    bid = model.body("generated_desk").id
    vertices = mesh.vertices @ data.xmat[bid].reshape(3, 3).T + data.xpos[bid]
    triangles = vertices[mesh.faces]
    source = [2.10, 2.18]
    target = [2.60, 2.18]
    probes = {
        name: {
            "center": xy,
            "height": top_height(triangles, xy),
            "footprint_heights": [
                top_height(triangles, np.asarray(xy) + [dx, dy])
                for dx in (-0.05, 0, 0.05)
                for dy in (-0.035, 0, 0.035)
            ],
        }
        for name, xy in (("source", source), ("target", target))
    }
    tested = []
    for x in (1.85, 1.90, 1.95):
        for y in (2.50, 2.45):
            q = seed.copy()
            q[:2] = [x, y]
            for localz in (-0.025, -0.04):
                goal = [
                    source[0] - 0.13,
                    source[1] - 0.05,
                    probes["source"]["height"] + 0.056 - localz,
                ]
                ik = solve(mujoco, model, q, np.asarray(goal), np.eye(3))
                tested.append(
                    {
                        "root_xy": [x, y],
                        "object_local": [0.13, 0.05, localz],
                        "wrist_goal": goal,
                        "ik": ik,
                    }
                )
    viable = [
        r
        for r in tested
        if r["ik"]["position_error_m"] < 0.005
        and r["ik"]["orientation_error_rad"] < 0.05
    ]
    save(
        root / "TABLE_REACH_PROBE.json",
        {
            "schema": "native-mug-table-reach-probe/v1",
            "physics_steps": 0,
            "native_desk_mesh": desk["source"],
            "native_desk_bounds_m": [
                vertices.min(0).tolist(),
                vertices.max(0).tolist(),
            ],
            "support": probes,
            "candidates": tested,
            "viable": viable,
            "not_a_dynamic_grasp_test": True,
            "implementation": _file_binding(Path(__file__)),
        },
    )
    print(
        {
            "support": probes,
            "viable": [
                {k: v for k, v in r.items() if k != "ik"}
                | {"error": r["ik"]["position_error_m"]}
                for r in viable
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
