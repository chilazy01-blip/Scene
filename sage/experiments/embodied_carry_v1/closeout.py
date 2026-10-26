"""Bind the successful locomotion delivery and the honest failed carry attempt."""

import argparse
from datetime import datetime
from pathlib import Path
import time
import json
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    sha256_file,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def close(root):
    output = root / "FINAL_REVIEW.json"
    if output.exists():
        raise FileExistsError(output)
    main = read_bound_json(root / "delivery/DELIVERY.json")
    carry = read_bound_json(root / "carry/attempt_01/RESULT.json")
    protocol = read_bound_json(root / "matrix_protocol_01/MATRIX.json")
    carry_protocol = read_bound_json(root / "carry/PROTOCOL.json")
    for b in [
        *protocol["dependencies"].values(),
        *carry_protocol["dependencies"].values(),
    ]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("frozen dependency changed")
    clock = json.loads((root / "CLOCK_ORIGIN.json").read_text())
    origin = datetime.fromisoformat(
        clock["origin_utc"].replace("Z", "+00:00")
    ).timestamp()
    deadline = datetime.fromisoformat(
        clock["two_hour_deadline_utc"].replace("Z", "+00:00")
    ).timestamp()
    metrics = []
    reports = []
    for item in protocol["cases"]:
        directory = root / "matrix_run_01" / item["id"]
        audit = read_bound_json(directory / "full/AUDIT.json")
        integrity = read_bound_json(directory / "full/REFERENCE_AUDIT.json")
        if not audit["task_passed"] or not integrity["passed"]:
            raise ValueError("accepted main trajectory no longer has accepted audits")
        metrics.append(audit["metrics"])
        for stage in ("admission", "short", "full"):
            r = read_bound_json(directory / stage / "REPORT.json")
            if sha256_file(Path(r["trace"]["path"])) != r["trace"]["sha256"]:
                raise ValueError("trace changed")
        reports.append(_file_binding(directory / "episode/EPISODE.json"))
    diagnoses = []
    for item in carry["outcomes"]:
        for key in ("report", "audit"):
            b = item[key]
            if sha256_file(Path(b["path"])) != b["sha256"]:
                raise ValueError("carry result changed")
        r = read_bound_json(Path(item["report"]["path"]))
        t = read_bound_json(Path(r["trace"]["path"]))
        ss = t["warmup_substeps"] + [s for row in t["records"] for s in row["substeps"]]
        diagnoses.append(
            {
                "report": item["report"],
                "physics_steps": len(ss),
                "sonic_active_writes": r["sonic_candidate_actuator_writes"],
                "opposing_finger_contact_steps": sum(
                    s["payload"]["opposing_finger_contact"] for s in ss
                ),
                "retained_within_30mm_steps": sum(s["payload"]["held"] for s in ss),
                "max_consecutive_retained_steps": max(
                    s["grip_consecutive_steps"] for s in ss
                ),
                "max_relative_position_movement_m": max(
                    s["payload"]["relative_position_error_m"] for s in ss
                ),
                "last_object_height_m": ss[-1]["payload"]["height_m"],
                "physical_gates": r["physical_gates"],
                "stop_reason": r["stop_reason"],
                "scientific_conclusion": (
                    "not admitted; initial-to-closed-grip displacement exceeded 30mm"
                    if r["stop_reason"] is None
                    else "not admitted; no opposing contact established and object fell below height guard"
                ),
            }
        )
    video_path = root / "carry/review_grasp_01/MANIFEST.json"
    video = read_bound_json(video_path)
    for b in video["artifacts"].values():
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("diagnostic video changed")
    result = {
        "schema": "locomotion-and-conditional-carry-final-review/v1",
        "main_goal_passed": main["classification"] == "accepted_development_pipeline"
        and all(main["gates"].values()),
        "main_goal_elapsed_s": main["accepted_utc_timestamp"] - origin,
        "main_completed_within_2h": main["accepted_utc_timestamp"] <= deadline,
        "main_delivery": _file_binding(root / "delivery/DELIVERY.json"),
        "development_episodes": 48,
        "samples_at_50hz": 14400,
        "accepted_simulated_time_s": 288,
        "target_error_m_range": [
            min(m["target_error_m"] for m in metrics),
            max(m["target_error_m"] for m in metrics),
        ],
        "max_final_second_drift_m": max(m["hold_drift_m"] for m in metrics),
        "max_final_second_speed_m_s": max(m["hold_speed_m_s"] for m in metrics),
        "episode_manifests": reports,
        "conditional_carry_attempt_completed": carry["engineering_error"] is None
        and len(carry["outcomes"]) > 0,
        "carry_attempt": _file_binding(root / "carry/attempt_01/RESULT.json"),
        "carry_diagnoses": diagnoses,
        "carry_diagnostic_video": _file_binding(video_path),
        "carry_walking_success_validated": False,
        "production_accepted": False,
        "held_out_evaluation": False,
        "test_result": "151 passed; no carry success inferred from unit tests",
        "manual_visual_review": {
            "main_cases": ["C001", "C025", "C048"],
            "carry": "grasp_01 observer diagnostic; actual hand/free cylinder visible; support and failure disclosed",
        },
        "next_bottleneck": "Physically compatible initial grasp and closure: initial placement was pushed roughly 46mm to its settled contact position. New protocol should explicitly separate measured grasp acquisition/settling from retention, with no object teleport or post-hoc threshold relaxation. Qualify unsupported standing before any walk.",
        "known_unexecuted_path_issue": "The v1 carry short-walk audit includes the final stop task gate, so it would reject a safe still-moving 2-second segment. No walking was executed. Before a future walking protocol, split safety/retention admission from full walk-stop task success in a new engine revision and regression-test both.",
        "implementation": _file_binding(Path(__file__)),
        "created_utc_timestamp": time.time(),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {
            k: result[k]
            for k in (
                "main_goal_passed",
                "main_goal_elapsed_s",
                "main_completed_within_2h",
                "conditional_carry_attempt_completed",
                "carry_walking_success_validated",
                "target_error_m_range",
                "max_final_second_drift_m",
            )
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    close(p.parse_args().root)
