"""Read-only scientific exit review; preserves all bounded attempts and costs."""

import argparse
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def run(root):
    import mujoco

    reports = []
    physics = active_steps = 0
    for version in range(1, 7):
        directory = root.parent / f"embodied_transport_20261020_v{version}"
        for path in sorted(directory.glob("*/*/REPORT.json")):
            r = read_bound_json(path)
            physics += r["physics_steps"]
            active_steps += r["active_physics_steps"]
            a = read_bound_json(path.with_name("AUDIT.json"))
            reports.append(
                {
                    "version": version,
                    "run": path.parent.name,
                    "report": _file_binding(path),
                    "audit": _file_binding(path.with_name("AUDIT.json")),
                    "physics_steps": r["physics_steps"],
                    "active_steps": r["active_physics_steps"],
                    "task_passed": a["task_passed"],
                    "control_passed": a["control_passed"],
                    "stop_reason": r["stop_reason"],
                    "final_stage": r["final_stage"],
                }
            )
    last = root / "attempt_01/active_1000/REPORT.json"
    r = read_bound_json(last)
    trace = read_bound_json(Path(r["trace"]["path"]))
    rows = [x for x in trace["records"] if x["sonic_candidate_consumed_by_physics"]]
    m = mujoco.MjModel.from_xml_path(r["model"]["path"])
    d = mujoco.MjData(m)
    w = m.body("right_wrist_yaw_link").id
    errors = []
    for row in rows:
        task = row["task"]
        if (
            task["reach_subphase"] == "preinsert"
            and row["reference_tick"] - task["sub_start"] >= 50
        ):
            d.qpos[:] = row["substeps"][-1]["full_qpos_after"]
            mujoco.mj_forward(m, d)
            errors.append(
                {
                    "frame": row["reference_tick"],
                    "actual_wrist_m": d.xpos[w].tolist(),
                    "frozen_preinsert_goal_m": task["sub_goal_m"],
                    "position_error_m": float(
                        np.linalg.norm(d.xpos[w] - task["sub_goal_m"])
                    ),
                    "orientation_error_rad": float(
                        np.linalg.norm(
                            Rotation.from_matrix(d.xmat[w].reshape(3, 3)).as_rotvec()
                        )
                    ),
                }
            )
    contact = next(
        (x for x in rows if x["substeps"][-1]["payload"]["hand_contact"]), None
    )
    source_loss = next(
        (x for x in rows if not x["substeps"][-1]["payload"]["source_supported"]), None
    )
    result = {
        "schema": "bounded-autonomous-transport-development-review/v1",
        "task_passed": False,
        "physics_steps": physics,
        "active_sonic_substeps": active_steps,
        "runs": reports,
        "completed_real_pickups": 0,
        "completed_full_transports": 0,
        "last_run": {
            "first_hand_contact_frame": contact["reference_tick"] if contact else None,
            "first_source_loss_frame": (
                source_loss["reference_tick"] if source_loss else None
            ),
            "last_object": rows[-1]["substeps"][-1]["payload"],
            "tracking_checks": errors,
        },
        "finding": "Six finite revisions have not established physical pickup. Kinematic reference clearance is not actual learned-policy tracking clearance; actual fingers push object off source before opposing grasp. Do not relabel this as successful pickup. Last IK rejection followed moving knocked object, not evidence of initial geometric unreachability.",
        "budget_exit": "first4 revisions and subsequent2-version ergonomic batch ended; no more same-object grasp physics without a newly justified route and protocol",
        "recommended_route": "ask user before changing sole-SONIC29 body control contract; task-space upper-limb control would need separate whole-body safety and balance qualification, starting with standing pick/place",
        "missing_guard": "future acquisition protocol should abort premature source loss/object displacement before acquired opposing grasp, rather than chasing a falling object; not retroactively applied to old data",
        "current_goal": "active, objective not achieved; controller-route choice pending, not goal complete",
        "initial_object_profiles": [
            {
                "versions": [1, 2, 3, 4],
                "height_m": 0.08,
                "mass_kg": 0.05,
                "support_top_m": 0.65,
            },
            {
                "versions": [5, 6],
                "height_m": 0.12,
                "mass_kg": 0.05,
                "support_top_m": 0.8,
            },
        ],
        "scope": "single generated room, privileged state feedback, development only; six failed revisions are not a general impossibility proof",
        "implementation": _file_binding(Path(__file__)),
        "review_physics_steps": 0,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    output = root / "BATCH_REVIEW.json"
    if output.exists():
        raise FileExistsError(output)
    write_json_atomic(output, result)
    print(
        {
            "physics_steps": physics,
            "active_steps": active_steps,
            "task_passed": False,
            "reports": len(reports),
            "first_contact": result["last_run"]["first_hand_contact_frame"],
            "first_source_loss": result["last_run"]["first_source_loss_frame"],
            "max_preinsert_tracking_m": max(x["position_error_m"] for x in errors),
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
