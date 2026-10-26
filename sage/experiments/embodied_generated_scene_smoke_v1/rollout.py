"""Run exactly one unchanged Source-A controller trajectory in the generated scene."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from sage.experiments.embodied_data_stability_v1.neutral_adapter import (
    DualLayerEpisodeWriter,
    SourceANativeParityAdapter,
    TaskInstruction,
    read_policy_episode,
    read_privileged_episode,
)
from sage.experiments.embodied_data_stability_v1.run_source_a_native import (
    NativeCounters,
    verify_source_contract,
)
from sage.experiments.embodied_data_stability_v1.trajectory_capture import (
    SourceAPhaseTrace,
    StateStreamCapture,
)

from .common import (
    REFERENCE_S3,
    RUN_ROOT,
    SOURCE,
    SOURCE_CONTRACT,
    read_json,
    sha256,
    write_json,
)
from .runtime import build_custom_sim, geom_label


class ContactAudit:
    """Record which pair caused penetration, not only its scalar maximum."""

    def __init__(self, state_capture: StateStreamCapture):
        self.state_capture = state_capture
        self.peak = {
            "penetration_m": 0.0,
            "sim_time_s": None,
            "physics_step": None,
            "pair": None,
        }
        self.pairs: dict[str, dict[str, Any]] = {}

    def on_step(self, model: Any, data: Any, step: int, mujoco: Any) -> None:
        self.state_capture.on_step(model, data, step, mujoco)
        for contact in data.contact:
            penetration = max(0.0, -float(contact.dist))
            left = geom_label(model, mujoco, int(contact.geom1))
            right = geom_label(model, mujoco, int(contact.geom2))
            pair = " <-> ".join(sorted((left, right)))
            row = self.pairs.setdefault(
                pair,
                {
                    "max_penetration_m": 0.0,
                    "contact_steps": 0,
                    "steps_above_2mm": 0,
                    "steps_above_10mm": 0,
                    "first_contact_time_s": float(data.time),
                    "last_contact_time_s": float(data.time),
                },
            )
            row["contact_steps"] += 1
            row["last_contact_time_s"] = float(data.time)
            row["max_penetration_m"] = max(row["max_penetration_m"], penetration)
            row["steps_above_2mm"] += int(penetration > 0.002)
            row["steps_above_10mm"] += int(penetration > 0.010)
            if penetration > self.peak["penetration_m"]:
                self.peak = {
                    "penetration_m": penetration,
                    "sim_time_s": float(data.time),
                    "physics_step": step,
                    "pair": pair,
                }

    def report(self) -> dict[str, Any]:
        ranked = sorted(
            ({"pair": pair, **row} for pair, row in self.pairs.items()),
            key=lambda row: row["max_penetration_m"],
            reverse=True,
        )
        return {"peak": self.peak, "pairs_by_max_penetration": ranked[:20]}


def run_rollout(run_root: Path) -> dict[str, Any]:
    started = time.monotonic()
    output = run_root / "trajectory_01"
    output.mkdir(exist_ok=False)
    model_path = run_root / "model/MODEL.xml"
    if not (run_root / "model/STATIC_VALIDATION.json").is_file():
        raise RuntimeError("static validation must pass before the single dynamic attempt")
    static = read_json(run_root / "model/STATIC_VALIDATION.json")
    if static.get("passed") is not True or static.get("physics_steps") != 0:
        raise RuntimeError("invalid static preflight")

    contract = read_json(SOURCE_CONTRACT)
    source_verification = verify_source_contract(SOURCE, contract)
    sys.path.insert(0, str(SOURCE))
    import mujoco
    import numpy as np
    import onnxruntime as ort
    from ik import pipeline, sim

    versions = {
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    mismatches = {
        key: {"expected": contract["environment"][key], "actual": value}
        for key, value in versions.items()
        if contract["environment"][key] != value
    }
    if mismatches:
        raise RuntimeError(f"runtime contract mismatch: {mismatches}")
    case = read_json(REFERENCE_S3 / "CASE_DRAW.json")
    # The generated model already encodes the finalized table layout. Reusing
    # the original S3 draw means no second table transform is applied here.
    kwargs = {
        "spawn": case["spawn"],
        "spawn_yaw": np.radians(case["spawn_yaw_deg"]),
        "cyl_xy": case["cyl_xy"],
        "cyl_mass_scale": case["cyl_mass_scale"],
        "cyl_friction": case["cyl_friction"],
        "brown_dz": 0.0,
        "blue_dz": 0.0,
        "brown_dxy": (0.0, 0.0),
        "blue_dxy": (0.0, 0.0),
    }
    write_json(
        output / "CASE_DRAW.json",
        {
            **case,
            "case_source": str(REFERENCE_S3 / "CASE_DRAW.json"),
            "case_source_sha256": sha256(REFERENCE_S3 / "CASE_DRAW.json"),
            "table_randomization_disabled_because_generated_layout_is_in_MODEL": True,
        },
    )
    write_json(
        output / "RUN_MANIFEST.json",
        {
            "schema": "embodied-generated-scene-controller-run/v1",
            "attempt_index": 1,
            "attempt_limit": 1,
            "model_path": str(model_path),
            "model_sha256": sha256(model_path),
            "controller_repository": contract["repo"],
            "controller_commit": contract["commit"],
            "runtime_versions": versions,
            "source_verification": source_verification,
            "max_physics_steps": 120000,
            "max_sim_seconds": 300.0,
            "rendering_during_physics": False,
            "training": False,
            "production_accepted": False,
        },
    )

    writer = DualLayerEpisodeWriter(
        output / "episode_contract",
        {
            "episode_id": "own-generated-scene-source-a-controller-01",
            "split": "development",
            "used_for_tuning": True,
            "candidate_id": "source_a_g1_manipulation_on_own_generated_scene",
            "controller_version": contract["commit"],
            "engine": f"mujoco-{mujoco.__version__}",
            "layout_seed": 26101501,
            "case_seed": case["seed"],
            "case_index": case["ep"],
            "head_rgbd_status": "not_recorded_bounded_isolation_smoke",
            "wrist_rgbd_status": "not_recorded_bounded_isolation_smoke",
        },
    )
    instruction = TaskInstruction(
        task_type="pick_carry_stop_place_release_retreat",
        target_object_semantic_id="red_light_cylinder",
        target_support_semantic_id="generated_side_table",
        target_region_semantic_id="clear_tabletop_region",
        natural_language="Pick up the light red object and place it on the side table.",
    )
    capture = StateStreamCapture(sample_every_steps=4, action_index=lambda: -1)
    capture.action_index = lambda: len(writer.policy_records) - 1
    contacts = ContactAudit(capture)
    phase_trace = SourceAPhaseTrace()
    counters = NativeCounters(
        mujoco,
        ort,
        max_physics_steps=120000,
        max_sim_seconds=300.0,
        on_step=contacts.on_step,
    )
    adapter = SourceANativeParityAdapter(
        writer,
        instruction,
        pipeline.PICK_STANCE,
        pipeline.PLACE_STANCE,
        time_provider=lambda: 0.0 if counters._data is None else float(counters._data.time),
    )
    if pipeline.COMMANDER is not None:
        raise RuntimeError("Source-A commander has pre-existing mutable state")
    pipeline.COMMANDER = adapter
    sim.OUT_DIR = output / "native_output"
    sim.OUT_DIR.mkdir()
    original_build = sim.build_sim
    sim.build_sim = lambda spawn=(-1.2, 0.15): build_custom_sim(SOURCE, model_path, spawn)
    result: dict[str, Any] = {}
    error = None
    phase_trace.install(pipeline)
    counters.install()
    try:
        result = pipeline.run_once(
            **kwargs,
            video=None,
            snapshots=False,
            sim_limit=300.0,
            wall_limit=850.0,
        )
    except BaseException:
        error = traceback.format_exc()
    finally:
        metrics = counters.close()
        phase_trace.restore(pipeline)
        sim.build_sim = original_build
        pipeline.COMMANDER = None

    final_time = float(result.get("sim_time_s", 0.0)) if result else 0.0
    writer.append_event(
        final_time,
        "source_phase_summary",
        {
            "phase": result.get("phase"),
            "phase_idx": result.get("phase_idx"),
            "success": result.get("success"),
            "predicates": result.get("ok"),
            "abort": result.get("abort"),
        },
    )
    contract_manifest = writer.finalize()
    policy_replay = read_policy_episode(output / "episode_contract")
    privileged_replay = read_privileged_episode(output / "episode_contract", explicit=True)
    contract_replay = bool(
        len(policy_replay) == len(privileged_replay) == 2
        and [row["decision_index"] for row in policy_replay] == [0, 1]
        and [row["decision_index"] for row in privileged_replay] == [0, 1]
    )
    state_manifest = capture.finalize(output / "state_stream")
    phase_events = phase_trace.with_approach(policy_replay)
    write_json(output / "PHASE_EVENTS.json", {"events": phase_events})
    contact_report = contacts.report()
    write_json(output / "CONTACT_DIAGNOSTICS.json", contact_report)

    task_ok = bool(
        not error
        and result.get("success")
        and all(result.get("ok", {}).get(key) is True for key in ("pick", "transport", "place"))
    )
    integrity_ok = bool(
        metrics["physics_steps"] > 0
        and metrics["policy_forwards"] > 0
        and metrics["nonfinite_steps"] == 0
        and metrics["external_wrench_violations"] == 0
        and metrics["state_continuity_violations"] == 0
        and contract_replay
    )
    def _number_or(value: Any, default: float) -> float:
        return default if value is None else float(value)

    quality = {
        "penetration_le_10mm": metrics["max_penetration_m"] <= 0.010,
        "contact_force_le_600n": metrics["max_contact_force_n"] <= 600.0,
        "carry_clearance_ge_minus_2mm": _number_or(
            result.get("carry_clear_min_m"), -1.0
        ) >= -0.002,
        "slip_le_70mm": _number_or(result.get("max_slip_m"), 1.0) <= 0.070,
        "pelvis_height_ge_650mm": _number_or(
            result.get("min_pelvis_z"), 0.0
        ) >= 0.650,
        "final_tilt_le_10deg": _number_or(
            result.get("final_tilt_deg"), 181.0
        ) <= 10.0,
    }
    reference = read_json(REFERENCE_S3 / "S3_RESULT.json")
    binding = read_json(run_root / "model/BINDING.json")
    report = {
        "schema": "embodied-generated-scene-controller-result/v1",
        "trajectory_executed": metrics["physics_steps"] > 0,
        "task_success": task_ok,
        "integrity_passed": integrity_ok,
        "motion_quality_passed": all(quality.values()),
        "classification": (
            "task_and_motion_pass" if task_ok and integrity_ok and all(quality.values())
            else "diagnostic"
        ),
        "source_result": result,
        "audit_metrics": metrics,
        "quality_checks": quality,
        "contact_diagnostics": contact_report,
        "phase_events": phase_events,
        "state_manifest": state_manifest,
        "decision_contract_manifest": contract_manifest,
        "comparison_to_original_s3": {
            "original_task_success": reference["end_to_end_task_passed"],
            "original_max_penetration_m": reference["metrics"]["max_penetration_m"],
            "generated_max_penetration_m": metrics["max_penetration_m"],
            "penetration_delta_m": (
                metrics["max_penetration_m"]
                - reference["metrics"]["max_penetration_m"]
            ),
            "original_min_carry_clearance_m": reference["metrics"][
                "min_carry_clearance_m"
            ],
            "generated_min_carry_clearance_m": result.get("carry_clear_min_m"),
        },
        "error": error,
        "wall_seconds": time.monotonic() - started,
        "attempts_used": 1,
        "attempt_limit": 1,
        "render_passes": 0,
        "training_updates": 0,
        "production_accepted": False,
        "long_run_authorized": False,
        "interpretation_boundary": binding.get(
            "interpretation_boundary",
            (
                "This run changes generated room/table visuals and rebuilds task-table proxies, "
                "but intentionally retains Source-A hand collision meshes and the analytic cylinder."
            ),
        ),
    }
    write_json(output / "RESULT.json", report)
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, default=RUN_ROOT)
    args = parser.parse_args(argv)
    try:
        report = run_rollout(args.run_root)
    except BaseException:
        error = traceback.format_exc()
        failure = args.run_root / "trajectory_01_runner_failure.json"
        write_json(failure, {"error": error, "production_accepted": False})
        print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "trajectory_executed": report["trajectory_executed"],
                "task_success": report["task_success"],
                "classification": report["classification"],
                "physics_steps": report["audit_metrics"]["physics_steps"],
                "max_penetration_m": report["audit_metrics"]["max_penetration_m"],
            },
            sort_keys=True,
        )
    )
    return 0 if report["trajectory_executed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

