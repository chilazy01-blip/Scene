"""Recover a truthful report from the one already-recorded aborted rollout.

This module never constructs or steps a MuJoCo simulation.  It only summarizes
the immutable state stream and per-step contact audit written before the generic
rollout reporter encountered a nullable Source-A metric.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np

from .common import RUN_ROOT, read_json, sha256, write_json


def recover(run_root: Path) -> dict:
    trajectory = run_root / "trajectory_01"
    state_path = trajectory / "state_stream/privileged_state.npz"
    contact_path = trajectory / "CONTACT_DIAGNOSTICS.json"
    phase_path = trajectory / "PHASE_EVENTS.json"
    event_path = trajectory / "episode_contract/events.jsonl"
    if (trajectory / "RESULT.json").exists():
        raise FileExistsError("RESULT.json already exists; refusing to overwrite it")

    with np.load(state_path, allow_pickle=False) as archive:
        physics_step = archive["physics_step"].copy()
        times = archive["sim_time_s"].copy()
        object_position = archive["object_position"].copy()
        object_quaternion = archive["object_quaternion_wxyz"].copy()
        max_force = archive["max_contact_force_n"].copy()
        min_distance = archive["min_contact_distance_m"].copy()
        finite = all(np.isfinite(archive[name]).all() for name in archive.files)

    import json

    events = [json.loads(line) for line in event_path.read_text().splitlines() if line]
    summary = next(row for row in events if row.get("event") == "source_phase_summary")
    contact = read_json(contact_path)
    phases = read_json(phase_path)["events"]
    pose_replay_path = run_root / "pose_replay/RESULT.json"
    pose_replay = read_json(pose_replay_path)
    binding = read_json(run_root / "model/BINDING.json")
    failure = read_json(run_root / "trajectory_01_runner_failure.json")

    peak = contact["peak"]
    report = {
        "schema": "embodied-generated-object-aborted-controller-result/v1",
        "report_recovered_without_physics": True,
        "trajectory_executed": bool(len(physics_step) and int(physics_step[-1]) > 0),
        "task_success": False,
        "classification": "diagnostic_abort_before_grasp",
        "source_phase_summary": summary,
        "abort": summary["details"].get("abort"),
        "abort_phase": summary["details"].get("phase"),
        "audit_metrics": {
            "physics_steps": int(physics_step[-1]),
            "sim_time_s": float(times[-1]),
            "recorded_samples": int(len(times)),
            "sample_every_physics_steps": 4,
            "all_recorded_arrays_finite": bool(finite),
            "max_penetration_m": float(peak["penetration_m"]),
            "max_penetration_pair": peak["pair"],
            "max_penetration_time_s": float(peak["sim_time_s"]),
            "max_contact_force_n_sampled": float(max_force.max()),
            "minimum_sampled_contact_distance_m": float(min_distance.min()),
        },
        "object_dynamics": {
            "initial_position_m": object_position[0].tolist(),
            "final_position_m": object_position[-1].tolist(),
            "minimum_center_z_m": float(object_position[:, 2].min()),
            "initial_quaternion_wxyz": object_quaternion[0].tolist(),
            "final_quaternion_wxyz": object_quaternion[-1].tolist(),
            "diagnosis": (
                "The generated mesh object tipped and penetrated the table before the "
                "grasp phase. Source-A then aborted with no_grasp_ik."
            ),
        },
        "contact_diagnostics": contact,
        "phase_events": phases,
        "same_qpos_contact_counterfactual": pose_replay,
        "same_qpos_contact_counterfactual_sha256": sha256(pose_replay_path),
        "comparison_validity": {
            "full_task_dynamic_penetration_comparable": False,
            "reason": "The generated object toppled before grasp, so no hand-object dynamic grasp occurred.",
            "same_qpos_geometric_contact_comparable": True,
        },
        "runner_reporting_failure": failure["error"],
        "runner_bug_fixed_in_source": True,
        "attempts_used": 1,
        "attempt_limit": 1,
        "additional_physics_steps_during_recovery": 0,
        "production_accepted": False,
        "interpretation_boundary": binding["interpretation_boundary"],
    }
    write_json(trajectory / "RESULT.json", report)
    write_json(trajectory / "RECOVERED_RESULT.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    report = recover(args.run_root)
    print(
        {
            "trajectory_executed": report["trajectory_executed"],
            "classification": report["classification"],
            "physics_steps": report["audit_metrics"]["physics_steps"],
            "max_penetration_m": report["audit_metrics"]["max_penetration_m"],
            "abort": report["abort"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
