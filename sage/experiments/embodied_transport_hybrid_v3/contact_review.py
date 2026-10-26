"""Zero-step comparison of actual released-object support contact manifolds."""

import argparse
from pathlib import Path
import numpy as np
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    path = root / "attempt_01/active_1000/REPORT.json"
    r = read_bound_json(path)
    t = read_bound_json(Path(r["trace"]["path"]))
    rows = [x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    m = mujoco.MjModel.from_xml_path(r["model"]["path"])
    m.opt.timestep = 0.005
    original = int(m.opt.enableflags)
    g = m.geom("payload_geom").id
    w = m.body("right_wrist_yaw_link").id
    checks = []
    for frame in (662, 727, len(rows) - 1):
        s = rows[frame]["substeps"][-1]
        for flag in (original, original | int(mujoco.mjtEnableBit.mjENBL_MULTICCD)):
            m.opt.enableflags = flag
            d = mujoco.MjData(m)
            d.qpos[:] = s["full_qpos_after"]
            d.qvel[:] = s["full_qvel_after"]
            d.ctrl[:] = s["all_ctrl"]
            d.qacc_warmstart[:] = s["qacc_warmstart_after"]
            mujoco.mj_forward(m, d)
            contacts = []
            for i, c in enumerate(d.contact):
                if g not in (c.geom1, c.geom2):
                    continue
                f = np.zeros(6)
                mujoco.mj_contactForce(m, d, i, f)
                contacts.append(
                    {
                        "other": m.geom(c.geom2 if c.geom1 == g else c.geom1).name,
                        "position_m": c.pos.tolist(),
                        "normal_force_n": float(f[0]),
                        "distance_m": float(c.dist),
                    }
                )
            checks.append(
                {
                    "frame": frame,
                    "enableflags": flag,
                    "contacts": contacts,
                    "input_linear_speed_m_s": float(
                        np.linalg.norm(s["payload"]["linear_velocity_m_s"])
                    ),
                }
            )
    m.opt.enableflags = original
    d = mujoco.MjData(m)
    x = rows[370]
    s = x["substeps"][0]
    d.qpos[:] = s["full_qpos_before"]
    mujoco.mj_forward(m, d)
    case = read_bound_json(Path(r["case"]["path"]))
    grasp = np.array(x["substeps"][0]["payload"]["world_position_m"]) - np.array(
        case["grasp_local_xyz_m"]
    )
    result = {
        "schema": "hybrid-placement-contact-review/v1",
        "report": _file_binding(path),
        "model": r["model"],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
        "checks": checks,
        "grasp_wrist_position_error_m": float(np.linalg.norm(d.xpos[w] - grasp)),
        "max_held_slip_m": r["max_retention_slip_m"],
        "body_min_pelvis_m": min(
            s["pelvis_height_m"] for row in rows for s in row["substeps"]
        ),
        "body_min_up": min(s["up_component"] for row in rows for s in row["substeps"]),
        "task_passed": False,
        "finding": "actual pickup,100substep source clearance, target placement, release and retraction observed; final instantaneous velocity gate fails. Default cylinder-on-cylinder manifold has one point; multiccd changes contact topology but zero-step review does not establish damping/stability. A separately frozen contact-fidelity batch and renewed full-episode admission are required; do not loosen velocity gate or reclassify this failed run.",
    }
    save(root / "CONTACT_REVIEW.json", result)
    print(
        {
            "grasp_wrist_error_m": result["grasp_wrist_position_error_m"],
            "max_slip_m": result["max_held_slip_m"],
            "body_min_pelvis_m": result["body_min_pelvis_m"],
            "body_min_up": result["body_min_up"],
            "contact_counts": [
                (x["frame"], x["enableflags"], len(x["contacts"])) for x in checks
            ],
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
