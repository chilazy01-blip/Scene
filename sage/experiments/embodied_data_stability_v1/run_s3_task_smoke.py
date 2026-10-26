"""Run the bounded S3 full-task smoke and emit the mandatory pause packet."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .neutral_adapter import TASK_PHASES, read_policy_episode
from .run_source_a_adapter_smoke import DEFAULT_S1_ROOT, run_attempt
from .run_source_a_native import DEFAULT_SOURCE_A_RUN
from .trajectory_capture import (
    SourceAPhaseTrace,
    StateStreamCapture,
    load_policy_state,
    load_privileged_state,
    sha256_file,
)


QUALITY_GATES = {
    "max_penetration_m": 0.010,
    "min_carry_clearance_m": -0.002,
    "max_contact_force_n": 600.0,
    "max_slip_m": 0.070,
    "min_pelvis_height_m": 0.65,
    "max_final_object_tilt_deg": 10.0,
    "max_policy_sample_period_s": 0.0200001,
    "head_rgbd_required_for_qualified": True,
}


def phase_gate(events: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row["phase"] for row in events]
    times = [float(row["sim_time_s"]) for row in events]
    return {
        "expected": list(TASK_PHASES),
        "observed": observed,
        "all_phases_present_once": observed == list(TASK_PHASES),
        "monotonic_timestamps": times == sorted(times),
        "state_or_contact_driven": all(
            row["source_event"].startswith(("report:", "snap:", "neutral_action:"))
            for row in events
        ),
    }


def run_s3(
    output_dir: Path,
    source_a_run: Path,
    baseline_result: Path,
    seed: int,
    episode_index: int,
) -> dict[str, Any]:
    started = time.monotonic()
    protocol = {
        "schema": "embodied-s3-task-smoke-protocol/v1",
        "candidate_id": "source_a_g1_manipulation",
        "task": "approach-align-grasp-lift-carry-stop-place-release-retreat",
        "seed": seed,
        "episode_index": episode_index,
        "attempt_limit": 1,
        "rendering": False,
        "bulk_rgbd": False,
        "training": False,
        "quality_gates_frozen_before_physics": QUALITY_GATES,
        "classification": {
            "qualified": "task, motion, and production-data gates all pass",
            "diagnostic": "audit data is intact but at least one task/motion/production gate fails",
            "invalid": "audit data is corrupt, unsynchronized, nonfinite, or unreadable",
        },
        "long_run_authorized": False,
    }
    protocol_path = output_dir / "S3_PROTOCOL.json"
    write_json_atomic(protocol_path, protocol)

    capture = StateStreamCapture(sample_every_steps=4, action_index=lambda: -1)
    trace = SourceAPhaseTrace()
    adapter_result = run_attempt(
        output_dir,
        source_a_run,
        baseline_result,
        seed,
        episode_index,
        max_physics_steps=120000,
        max_sim_seconds=300.0,
        state_capture=capture,
        phase_trace=trace,
    )
    state_manifest = capture.finalize(output_dir / "state_stream")
    policy_state = load_policy_state(output_dir / "state_stream")
    privileged_state = load_privileged_state(output_dir / "state_stream", explicit=True)
    policy_decisions = read_policy_episode(output_dir / "episode_contract")
    phase_events = trace.with_approach(policy_decisions)
    phase_report = phase_gate(phase_events)
    write_json_atomic(
        output_dir / "PHASE_EVENTS.json",
        {
            "schema": "embodied-s3-phase-events/v1",
            "events": phase_events,
            "gate": phase_report,
        },
    )

    source = adapter_result["source_result"]
    metrics = adapter_result["audit_metrics"]
    task_gates = {
        "native_task_success": source.get("success") is True,
        "pick": source.get("ok", {}).get("pick") is True,
        "transport": source.get("ok", {}).get("transport") is True,
        "place": source.get("ok", {}).get("place") is True,
        "released": any(row["phase"] == "release" for row in phase_events),
        "retreated": any(row["phase"] == "retreat" for row in phase_events),
        "all_nine_phases": phase_report["all_phases_present_once"],
        "monotonic_phase_events": phase_report["monotonic_timestamps"],
        "event_driven_phase_evidence": phase_report["state_or_contact_driven"],
    }
    motion_gates = {
        "finite": metrics["nonfinite_steps"] == 0,
        "no_external_wrench": metrics["external_wrench_violations"] == 0,
        "state_continuity": metrics["state_continuity_violations"] == 0,
        "no_fall": source.get("fell") is False,
        "pelvis_height": source.get("min_pelvis_z", 0) >= QUALITY_GATES["min_pelvis_height_m"],
        "penetration": metrics["max_penetration_m"] <= QUALITY_GATES["max_penetration_m"],
        "contact_force": metrics["max_contact_force_n"] <= QUALITY_GATES["max_contact_force_n"],
        "carry_clearance": (
            source.get("carry_clear_min_m", float("-inf"))
            >= QUALITY_GATES["min_carry_clearance_m"]
        ),
        "slip": source.get("max_slip_m", float("inf")) <= QUALITY_GATES["max_slip_m"],
        "final_tilt": (
            source.get("final_tilt_deg", float("inf"))
            <= QUALITY_GATES["max_final_object_tilt_deg"]
        ),
    }
    policy_times = policy_state["sim_time_s"]
    privileged_times = privileged_state["sim_time_s"]
    import numpy as np

    data_gates = {
        "adapter_contract_replay": adapter_result["contract_replay_passed"] is True,
        "state_stream_nonempty": int(state_manifest["sample_count"]) > 0,
        "policy_privileged_counts_match": len(policy_times) == len(privileged_times),
        "policy_privileged_timestamps_match": bool(np.array_equal(policy_times, privileged_times)),
        "sample_period": bool(
            len(policy_times) > 1
            and np.max(np.diff(policy_times)) <= QUALITY_GATES["max_policy_sample_period_s"]
        ),
        "state_stream_replay": bool(
            policy_state["joint_position"].shape[0] == state_manifest["sample_count"]
            and privileged_state["qpos"].shape[0] == state_manifest["sample_count"]
        ),
        "head_rgbd_present": False,
    }
    task_passed = all(task_gates.values())
    motion_passed = all(motion_gates.values())
    audit_data_complete = all(value for key, value in data_gates.items() if key != "head_rgbd_present")
    production_data_complete = all(data_gates.values())
    qualified = task_passed and motion_passed and production_data_complete
    classification = "qualified" if qualified else ("diagnostic" if audit_data_complete else "invalid")

    result = {
        "schema": "embodied-s3-task-smoke-result/v1",
        "candidate_id": "source_a_g1_manipulation",
        "task_smoke_executed": True,
        "end_to_end_task_passed": task_passed,
        "motion_quality_passed": motion_passed,
        "audit_data_complete": audit_data_complete,
        "production_data_complete": production_data_complete,
        "classification": classification,
        "qualified": qualified,
        "task_gates": task_gates,
        "motion_gates": motion_gates,
        "data_gates": data_gates,
        "quality_gates": QUALITY_GATES,
        "phase_gate": phase_report,
        "metrics": {
            "physics_steps": metrics["physics_steps"],
            "policy_forwards": metrics["policy_forwards"],
            "sim_time_s": source["sim_time_s"],
            "wall_seconds": time.monotonic() - started,
            "max_penetration_m": metrics["max_penetration_m"],
            "max_contact_force_n": metrics["max_contact_force_n"],
            "min_carry_clearance_m": source.get("carry_clear_min_m"),
            "max_slip_m": source.get("max_slip_m"),
            "min_pelvis_height_m": source.get("min_pelvis_z"),
            "final_object_tilt_deg": source.get("final_tilt_deg"),
            "state_samples": state_manifest["sample_count"],
        },
        "artifacts": {
            "protocol": {"path": str(protocol_path), "sha256": sha256_file(protocol_path)},
            "adapter_result": "RESULT.json",
            "phase_events": "PHASE_EVENTS.json",
            "decision_contract": "episode_contract/MANIFEST.json",
            "state_stream": "state_stream/MANIFEST.json",
        },
        "failed_quality_gates": [
            f"motion.{key}" for key, value in motion_gates.items() if not value
        ]
        + [f"data.{key}" for key, value in data_gates.items() if not value],
        "manual_interventions": 0,
        "render_passes": 0,
        "training_updates": 0,
        "production_accepted": False,
        "learning_validated": False,
        "mandatory_pause_reached": True,
        "long_run_authorized": False,
    }
    write_json_atomic(output_dir / "S3_RESULT.json", result)
    total_bytes = sum(path.stat().st_size for path in output_dir.rglob("*") if path.is_file())
    pause_packet = {
        "schema": "embodied-s3-mandatory-pause/v1",
        "mandatory_pause_reached": True,
        "smoke_attempts": 1,
        "smoke_classification": classification,
        "full_task_success": task_passed,
        "production_accepted": False,
        "learning_validated": False,
        "long_run_authorized": False,
        "observed_cost": {
            "wall_seconds": result["metrics"]["wall_seconds"],
            "sim_seconds": source["sim_time_s"],
            "physics_steps": metrics["physics_steps"],
            "policy_forwards": metrics["policy_forwards"],
            "artifact_bytes_before_pause_packet": total_bytes,
        },
        "twenty_episode_linear_projection_without_rgbd": {
            "wall_seconds": result["metrics"]["wall_seconds"] * 20,
            "artifact_bytes": total_bytes * 20,
            "status": "planning_estimate_only_not_authorized",
        },
        "rgbd_storage_projection": "unknown_not_measured",
        "blocking_risks_before_long_run": result["failed_quality_gates"],
        "decision_required": (
            "Keep this diagnostic smoke as a regression case and decide whether S3 quality "
            "repair should address collision/clearance and bounded RGB-D capture before any batch."
        ),
    }
    write_json_atomic(output_dir / "PAUSE_PACKET.json", pause_packet)
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-a-run", type=Path, default=DEFAULT_SOURCE_A_RUN)
    parser.add_argument(
        "--baseline-result",
        type=Path,
        default=DEFAULT_S1_ROOT / "source_a_native_01" / "RESULT.json",
    )
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--episode-index", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = run_s3(
            args.output_dir,
            args.source_a_run,
            args.baseline_result,
            args.seed,
            args.episode_index,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "S3_RUNNER_FAILURE.json",
            {
                "schema": "embodied-s3-runner-failure/v1",
                "error": error,
                "production_accepted": False,
                "long_run_authorized": False,
            },
        )
        print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "task_smoke_executed": result["task_smoke_executed"],
                "classification": result["classification"],
                "mandatory_pause_reached": result["mandatory_pause_reached"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["task_smoke_executed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
