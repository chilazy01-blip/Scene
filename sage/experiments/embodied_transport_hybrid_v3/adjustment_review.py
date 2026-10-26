"""Evidence-backed handoff of the controller adjustment, not transport acceptance."""

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
    report_path = root / "attempt_01/active_1000/REPORT.json"
    r = read_bound_json(report_path)
    a = read_bound_json(report_path.with_name("AUDIT.json"))
    t = read_bound_json(Path(r["trace"]["path"]))
    rows = [x for x in t["records"] if x["sonic_candidate_consumed_by_physics"]]
    events = r["task_events"]
    order = [e["to"] for e in events]
    place = next(e["frame"] for e in events if e["to"] == "place")
    lift = [
        s
        for x in rows
        if place - 25 <= x["reference_tick"] < place
        for s in x["substeps"]
    ]
    tail = [s for x in rows[-25:] for s in x["substeps"]]
    physics = active = 0
    reports = []
    for version in range(1, 4):
        for path in sorted(
            (root.parent / f"embodied_transport_hybrid_20261020_v{version}").glob(
                "attempt_01/*/REPORT.json"
            )
        ):
            d = read_bound_json(path)
            physics += d["physics_steps"]
            active += d["active_physics_steps"]
            reports.append(_file_binding(path))
    result = {
        "schema": "authorized-controller-adjustment-review/v1",
        "implementation": _file_binding(Path(__file__)),
        "report": _file_binding(report_path),
        "audit": _file_binding(report_path.with_name("AUDIT.json")),
        "controller_adjusted": True,
        "control_contract": r["control_contract"],
        "task_mode": r["task_mode"],
        "standing_qualification_passed": a["task_passed"],
        "full_transport_passed": False,
        "ordered_observed_stages": order,
        "real_lift100_substeps": len(lift) == 100
        and all(
            s["payload"]["opposing"]
            and not s["payload"]["source_supported"]
            and not s["payload"]["target_supported"]
            and s["payload"]["bottom_z_m"] >= 0.82
            for s in lift
        ),
        "minimum_lift_clearance_m": min(s["payload"]["bottom_z_m"] - 0.8 for s in lift),
        "max_held_slip_m": r["max_retention_slip_m"],
        "target_supported_final100_substeps": all(
            s["payload"]["target_supported"] for s in tail
        ),
        "hand_free_final100_substeps": all(
            not s["payload"]["hand_contact"] for s in tail
        ),
        "final100_peak_object_speed_m_s": float(
            max(np.linalg.norm(s["payload"]["linear_velocity_m_s"]) for s in tail)
        ),
        "required_object_speed_m_s": 0.02,
        "final100_xy_drift_m": float(
            max(
                np.linalg.norm(
                    np.array(s["payload"]["world_position_m"])[:2]
                    - tail[0]["payload"]["world_position_m"][:2]
                )
                for s in tail
            )
        ),
        "physics_steps_this_three_version_batch": physics,
        "active_hybrid_motor_substeps": active,
        "all_reports": reports,
        "contact_review": _file_binding(root / "CONTACT_REVIEW.json"),
        "replay": _file_binding(root / "diagnostic_pick_place/MANIFEST.json"),
        "replay_manually_viewed": True,
        "qualified_training_episode_exported": False,
        "scope": "single generated room,50g12cm cylinder, privileged state feedback; continuous standing pickup/transfer/release observed but final stability gate failed; not autonomous walking transport",
        "next_step": "separate finite contact-fidelity qualification: compare support contact manifold/solver stability without loosening20mm/s or hand-free window; new admission required for any model change; only after standing passes introduce continuous approach/carry walk",
        "review_physics_steps": 0,
    }
    save(root / "ADJUSTMENT_REVIEW.json", result)
    print(
        {
            k: result[k]
            for k in (
                "controller_adjusted",
                "standing_qualification_passed",
                "full_transport_passed",
                "real_lift100_substeps",
                "final100_peak_object_speed_m_s",
                "final100_xy_drift_m",
                "physics_steps_this_three_version_batch",
            )
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
