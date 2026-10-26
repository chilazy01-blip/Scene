"""Run one bounded Source-A contact/clearance repair smoke.

This is a development comparison against the frozen S3 diagnostic, not a
production batch and not an authorization to proceed to S4.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .neutral_adapter import TASK_PHASES, read_policy_episode, read_privileged_episode
from .run_s3_task_smoke import QUALITY_GATES, phase_gate
from .run_source_a_adapter_smoke import DEFAULT_S1_ROOT, run_attempt
from .run_source_a_native import DEFAULT_SOURCE_A_RUN, sha256_file
from .source_a_quality_repair import (
    DEFAULT_CONFIG_PATH,
    SourceAQualityRepairRuntime,
    load_repair_config,
)
from .trajectory_capture import (
    SourceAPhaseTrace,
    StateStreamCapture,
    load_policy_state,
    load_privileged_state,
)


def _at_most(value: Any, limit: float) -> bool:
    return value is not None and float(value) <= limit


def _at_least(value: Any, limit: float) -> bool:
    return value is not None and float(value) >= limit


def run_repair_smoke(
    output_dir: Path,
    source_a_run: Path,
    baseline_result: Path,
    config_path: Path,
    seed: int,
    episode_index: int,
) -> dict[str, Any]:
    started = time.monotonic()
    config = load_repair_config(config_path)
    protocol = {
        "schema": "embodied-source-a-quality-repair-protocol/v1",
        "candidate_id": "source_a_g1_manipulation",
        "controller_id": config.controller_id,
        "task": "approach-align-grasp-lift-carry-stop-place-release-retreat",
        "seed": seed,
        "episode_index": episode_index,
        "attempt_limit": 1,
        "rendering": False,
        "bulk_rgbd": False,
        "training": False,
        "pinned_source_modified": False,
        "sonic_used": False,
        "quality_gates_frozen_from_s3": QUALITY_GATES,
        "repair_config": {
            "path": str(config_path),
            "sha256": sha256_file(config_path),
        },
        "repair_implementation": {
            "runtime_sha256": sha256_file(Path(__file__).with_name("source_a_quality_repair.py")),
            "runner_sha256": sha256_file(Path(__file__)),
        },
        "scope": {
            "finger_actuators": "contact-aware per physical finger",
            "touchdown_release": "stop-on-support, unload, confirm, staged-open",
            "carry_path": "collision-primitive clearance preflight and bounded replan",
            "foot_ground": "diagnostic categorization only; no controller change",
        },
        "long_run_authorized": False,
    }
    write_json_atomic(output_dir / "REPAIR_PROTOCOL.json", protocol)

    capture = StateStreamCapture(sample_every_steps=4, action_index=lambda: -1)
    trace = SourceAPhaseTrace()
    runtime = SourceAQualityRepairRuntime(config)
    attempt_dir = output_dir / "attempt"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    attempt = run_attempt(
        attempt_dir,
        source_a_run,
        baseline_result,
        seed,
        episode_index,
        max_physics_steps=120000,
        max_sim_seconds=300.0,
        state_capture=capture,
        phase_trace=trace,
        runtime_overlay=runtime,
    )
    state_manifest = capture.finalize(output_dir / "state_stream")
    policy_state = load_policy_state(output_dir / "state_stream")
    privileged_state = load_privileged_state(output_dir / "state_stream", explicit=True)
    policy_decisions = read_policy_episode(attempt_dir / "episode_contract")
    privileged_decisions = read_privileged_episode(
        attempt_dir / "episode_contract", explicit=True
    )
    phase_events = trace.with_approach(policy_decisions)
    phase_report = phase_gate(phase_events)
    write_json_atomic(
        output_dir / "PHASE_EVENTS.json",
        {
            "schema": "embodied-source-a-quality-repair-phase-events/v1",
            "events": phase_events,
            "gate": phase_report,
        },
    )

    source = attempt["source_result"]
    metrics = attempt["audit_metrics"]
    overlay = attempt.get("runtime_overlay") or {}
    support = overlay.get("support_release") or {}
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
        "pelvis_height": _at_least(
            source.get("min_pelvis_z"), QUALITY_GATES["min_pelvis_height_m"]
        ),
        "penetration": _at_most(
            metrics.get("max_penetration_m"), QUALITY_GATES["max_penetration_m"]
        ),
        "contact_force": _at_most(
            metrics.get("max_contact_force_n"), QUALITY_GATES["max_contact_force_n"]
        ),
        "carry_clearance": _at_least(
            source.get("carry_clear_min_m"), QUALITY_GATES["min_carry_clearance_m"]
        ),
        "slip": _at_most(source.get("max_slip_m"), QUALITY_GATES["max_slip_m"]),
        "final_tilt": _at_most(
            source.get("final_tilt_deg"), QUALITY_GATES["max_final_object_tilt_deg"]
        ),
        "support_confirmed_before_open": support.get("confirmed") is True,
    }

    import numpy as np

    policy_times = policy_state["sim_time_s"]
    privileged_times = privileged_state["sim_time_s"]
    data_gates = {
        # S2's parity check requires exactly two decisions.  A task that ends
        # before the place commander legitimately has one, so repair quality
        # uses stream integrity/count alignment instead of that parity-only
        # cardinality assertion.
        "contract_stream_integrity": bool(
            len(policy_decisions) == len(privileged_decisions) >= 1
            and [row["decision_index"] for row in policy_decisions]
            == [row["decision_index"] for row in privileged_decisions]
        ),
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
    contact_categories = metrics.get("contact_categories", {})
    result = {
        "schema": "embodied-source-a-quality-repair-result/v1",
        "candidate_id": "source_a_g1_manipulation",
        "controller_id": config.controller_id,
        "repair_smoke_executed": True,
        "classification": classification,
        "qualified": qualified,
        "end_to_end_task_passed": task_passed,
        "motion_quality_passed": motion_passed,
        "audit_data_complete": audit_data_complete,
        "production_data_complete": production_data_complete,
        "task_gates": task_gates,
        "motion_gates": motion_gates,
        "data_gates": data_gates,
        "quality_gates": QUALITY_GATES,
        "phase_gate": phase_report,
        "metrics": {
            "physics_steps": metrics["physics_steps"],
            "policy_forwards": metrics["policy_forwards"],
            "sim_time_s": source.get("sim_time_s"),
            "wall_seconds": time.monotonic() - started,
            "max_penetration_m": metrics.get("max_penetration_m"),
            "max_contact_force_n": metrics.get("max_contact_force_n"),
            "min_carry_clearance_m": source.get("carry_clear_min_m"),
            "max_slip_m": source.get("max_slip_m"),
            "min_pelvis_height_m": source.get("min_pelvis_z"),
            "final_object_tilt_deg": source.get("final_tilt_deg"),
            "state_samples": state_manifest["sample_count"],
            "contact_categories": contact_categories,
        },
        "repair_evidence": overlay,
        "source_error": source.get("error"),
        "failed_quality_gates": [
            f"task.{key}" for key, value in task_gates.items() if not value
        ]
        + [f"motion.{key}" for key, value in motion_gates.items() if not value]
        + [f"data.{key}" for key, value in data_gates.items() if not value],
        "artifacts": {
            "protocol": "REPAIR_PROTOCOL.json",
            "attempt_result": "attempt/RESULT.json",
            "phase_events": "PHASE_EVENTS.json",
            "state_stream": "state_stream/MANIFEST.json",
        },
        "manual_interventions": 0,
        "render_passes": 0,
        "training_updates": 0,
        "production_accepted": False,
        "learning_validated": False,
        "long_run_authorized": False,
    }
    write_json_atomic(output_dir / "REPAIR_RESULT.json", result)
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
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--episode-index", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = run_repair_smoke(
            args.output_dir,
            args.source_a_run,
            args.baseline_result,
            args.config,
            args.seed,
            args.episode_index,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "REPAIR_RUNNER_FAILURE.json",
            {
                "schema": "embodied-source-a-quality-repair-runner-failure/v1",
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
                "classification": result["classification"],
                "task_passed": result["end_to_end_task_passed"],
                "motion_quality_passed": result["motion_quality_passed"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
