"""Independently verify saved SONIC takeover evidence, without running physics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_native_dynamic_shadow import official_control_arrays
from .sonic_native_planner_preflight import _file_binding
from .sonic_semantic_shadow import (
    ACTION_SCALES,
    DEFAULT_ANGLES,
    ISAACLAB_TO_MUJOCO,
)


def read_bound_json(path: Path) -> dict:
    document = json.loads(path.read_text())
    body = {
        key: value
        for key, value in document.items()
        if key != "content_sha256_excluding_this_field"
    }
    if canonical_sha256(body) != document.get("content_sha256_excluding_this_field"):
        raise ValueError(f"content hash mismatch: {path}")
    return document


def audit_execution(root: Path) -> dict:
    import numpy as np

    report_path = root / "REPORT.json"
    report = read_bound_json(report_path)
    trace_path = Path(report["trace"]["path"])
    if sha256_file(trace_path) != report["trace"]["sha256"]:
        raise ValueError("active trace file hash mismatch")
    trace = read_bound_json(trace_path)
    for binding in [*report["inputs"].values(), *report["source_bindings"].values()]:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError(f"input/source changed: {binding['path']}")
    admission_binding = report["admission"]
    admission_path = Path(admission_binding["path"])
    if sha256_file(admission_path) != admission_binding["sha256"]:
        raise ValueError("admission report changed")
    admission = read_bound_json(admission_path)
    prior_trace_path = Path(admission["trace"]["path"])
    if sha256_file(prior_trace_path) != admission["trace"]["sha256"]:
        raise ValueError("admission trace changed")
    prior = read_bound_json(prior_trace_path)
    rows = trace["records"]
    active = [row for row in rows if row["sonic_candidate_consumed_by_physics"]]
    prefix_matches = len(rows) == 150 and len(prior["records"]) >= 50
    for row, old in zip(rows[:50], prior["records"][:50]):
        for key in (
            "candidate_rad", "encoder_input_sha256", "decoder_input_sha256",
            "actual_qpos", "actual_qvel", "actual_quaternion", "actual_gyro",
        ):
            prefix_matches &= row[key] == old[key]
        prefix_matches &= not row["sonic_candidate_consumed_by_physics"]

    controls = {
        name: np.asarray(values) for name, values in official_control_arrays().items()
    }
    max_transform_error = max_pd_error = 0.0
    for row in active:
        raw = np.asarray(row["raw_action_isaaclab"])
        target = (
            np.asarray(DEFAULT_ANGLES)
            + raw[list(ISAACLAB_TO_MUJOCO)] * np.asarray(ACTION_SCALES)
        )
        max_transform_error = max(
            max_transform_error,
            float(np.max(np.abs(target - row["candidate_rad"]))),
        )
        expected_torque = np.clip(
            controls["kp"] * (target - row["actual_qpos"])
            - controls["kd"] * row["actual_qvel"],
            -controls["effort_limit"], controls["effort_limit"],
        )
        max_pd_error = max(
            max_pd_error,
            float(np.max(np.abs(
                expected_torque - row["substeps"][0]["body_torque_nm"]
            ))),
        )
    samples = [sample for row in rows for sample in row["substeps"]]
    samples += trace["warmup_substeps"]
    physical = {
        key: all(sample[key] for sample in samples)
        for key in (
            "finite", "only_declared_support_wrench", "pelvis_height", "upright",
            "penetration", "contact_force",
        )
    }
    active_steps = sum(len(row["substeps"]) for row in active)
    gates = {
        "report_passed": report["classification"] == "passed",
        "exact_50_tick_real_state_prefix": bool(prefix_matches),
        "exact_100_active_ticks_400_steps": len(active) == 100 and active_steps == 400,
        "all_active_candidates_guard_safe": all(row["candidate_safe"] for row in active),
        "raw_action_transform_exact": max_transform_error == 0.0,
        "official_pd_exact_at_every_active_tick_start": max_pd_error == 0.0,
        "all_physical_samples_passed": all(physical.values()),
        "no_source_a": (
            report["source_a_body_reference_used"] is False
            and report["source_a_body_command_used"] is False
        ),
        "no_early_stop": report["stop_reason"] is None,
    }
    audit = {
        "schema": "sonic-supported-execution-audit/v1",
        "classification": "passed" if all(gates.values()) else "failed",
        "report": _file_binding(report_path),
        "trace": _file_binding(trace_path),
        "implementation": _file_binding(Path(__file__)),
        "gates": gates,
        "metrics": {
            "active_ticks": len(active), "active_physics_steps": active_steps,
            "minimum_pelvis_height_m": min(x["pelvis_height_m"] for x in samples),
            "minimum_up_component": min(x["up_component"] for x in samples),
            "maximum_penetration_m": max(x["penetration_m"] for x in samples),
            "maximum_contact_force_n": max(x["contact_force_n"] for x in samples),
            "active_ticks_with_ground_contact": sum(
                any(x["contact_force_n"] > 0 for x in row["substeps"])
                for row in active
            ),
            "maximum_candidate_step_rad": report["maximum_candidate_step_rad"],
            "maximum_raw_target_transform_error_rad": max_transform_error,
            "maximum_first_substep_pd_error_nm": max_pd_error,
            "maximum_measured_joint_excursion_rad": float(np.max(np.ptp(
                np.asarray([row["actual_qpos"] for row in active]), axis=0
            ))) if active else 0.0,
        },
        "limits": {
            "supported_paused_reference_only": True,
            "full_mesh_collision_validated": False,
            "walking_validated": False, "free_standing_validated": False,
            "grasp_success_validated": False, "production_accepted": False,
            "torque_recomputation_scope": (
                "first physical substep of each of the 100 active ticks; "
                "all 400 substeps have recorded torque and physical gates"
            ),
        },
        "physics_executed_by_auditor": False,
    }
    audit["content_sha256_excluding_this_field"] = canonical_sha256(audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("audit output already exists")
    audit = audit_execution(args.run_root)
    write_json_atomic(args.output, audit)
    print(json.dumps(audit, indent=2))
    return 0 if audit["classification"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
