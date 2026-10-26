"""Run one S2 Source-A native-parity smoke through the neutral adapter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .neutral_adapter import (
    DualLayerEpisodeWriter,
    SourceANativeParityAdapter,
    TaskInstruction,
    read_policy_episode,
    read_privileged_episode,
)
from .run_source_a_native import (
    DEFAULT_SOURCE_A_RUN,
    NativeCounters,
    json_safe,
    read_json,
    sha256_file,
    verify_source_contract,
)


DEFAULT_S1_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s1_20261014_v1"
)


def equivalent(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            equivalent(left[key], right[key], tolerance) for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            equivalent(a, b, tolerance) for a, b in zip(left, right)
        )
    return left == right


def parity_fields(result: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": result.get("success"),
        "phase": result.get("phase"),
        "phase_idx": result.get("phase_idx"),
        "ok": result.get("ok"),
        "base_at_grasp": result.get("base_at_grasp"),
        "base_at_place": result.get("base_at_place"),
        "cyl_final": result.get("cyl_final"),
        "place_err_m": result.get("place_err_m"),
        "max_slip_m": result.get("max_slip_m"),
        "min_pelvis_z": result.get("min_pelvis_z"),
        "sim_time_s": result.get("sim_time_s"),
        "physics_steps": metrics.get("physics_steps"),
        "policy_forwards": metrics.get("policy_forwards"),
        "max_penetration_m": metrics.get("max_penetration_m"),
        "max_contact_force_n": metrics.get("max_contact_force_n"),
        "external_wrench_violations": metrics.get("external_wrench_violations"),
        "state_continuity_violations": metrics.get("state_continuity_violations"),
        "nonfinite_steps": metrics.get("nonfinite_steps"),
    }


def run_attempt(
    output_dir: Path,
    source_a_run: Path,
    baseline_result_path: Path,
    seed: int,
    episode_index: int,
    max_physics_steps: int,
    max_sim_seconds: float,
    state_capture: Any | None = None,
    phase_trace: Any | None = None,
    runtime_overlay: Any | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    baseline_report = read_json(baseline_result_path)
    if not baseline_report.get("native_reproduction_passed"):
        raise RuntimeError("native baseline did not pass")
    branch = source_a_run / "branches" / "A"
    source = branch / "source"
    source_contract_path = branch / "SOURCE_CONTRACT.json"
    source_contract = read_json(source_contract_path)
    verification = verify_source_contract(source, source_contract)
    manifest = {
        "schema": "embodied-s2-adapter-smoke-manifest/v1",
        "candidate_id": "source_a_g1_manipulation",
        "adapter": "controller_neutral_source_a_native_parity/v1",
        "runtime_overlay": (
            None
            if runtime_overlay is None
            else getattr(runtime_overlay.config, "controller_id", type(runtime_overlay).__name__)
        ),
        "repository": source_contract["repo"],
        "commit": source_contract["commit"],
        "source_contract": {
            "path": str(source_contract_path),
            "sha256": sha256_file(source_contract_path),
        },
        "native_baseline": {
            "path": str(baseline_result_path),
            "sha256": sha256_file(baseline_result_path),
        },
        "seed": seed,
        "episode_index": episode_index,
        "rendering": False,
        "training": False,
        "snapshots": False,
        "budgets": {
            "max_physics_steps": max_physics_steps,
            "max_sim_seconds": max_sim_seconds,
        },
        **verification,
    }
    write_json_atomic(output_dir / "RUN_MANIFEST.json", manifest)

    sys.path.insert(0, str(source))
    import mujoco
    import numpy as np
    import onnxruntime as ort

    versions = {
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    expected_versions = source_contract["environment"]
    mismatches = {
        key: {"expected": expected_versions[key], "actual": actual}
        for key, actual in versions.items()
        if expected_versions.get(key) != actual
    }
    write_json_atomic(
        output_dir / "PREFLIGHT.json",
        {
            "schema": "embodied-s2-adapter-preflight/v1",
            "runtime_versions": versions,
            "expected_versions": expected_versions,
            "runtime_contract_matches": not mismatches,
            "mismatches": mismatches,
        },
    )
    if mismatches:
        raise RuntimeError(f"runtime contract mismatch: {mismatches}")

    from ik import pipeline
    from ik import sim

    spec = importlib.util.spec_from_file_location("source_a_adapter_sweep", source / "eval/sweep.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the pinned Source-A sweep module")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    bounds, nominal = sweep.table_bounds(sweep.PRESETS["shipped"].get("cyl_margin_m", 0.045))
    scene = sweep.make_episode(episode_index, seed, "shipped", bounds, nominal)
    kwargs = {
        key: scene[key]
        for key in (
            "spawn",
            "cyl_xy",
            "cyl_mass_scale",
            "cyl_friction",
            "brown_dz",
            "blue_dz",
            "brown_dxy",
            "blue_dxy",
        )
    }
    kwargs["spawn_yaw"] = scene["spawn_yaw_deg"] * np.pi / 180.0
    write_json_atomic(output_dir / "CASE_DRAW.json", json_safe(scene))
    sim.OUT_DIR = output_dir / "native_output"
    sim.OUT_DIR.mkdir(parents=True, exist_ok=True)
    if pipeline.COMMANDER is not None:
        raise RuntimeError("pinned pipeline already has mutable commander state")

    writer = DualLayerEpisodeWriter(
        output_dir / "episode_contract",
        {
            "episode_id": "source-a-s2-native-parity-01",
            "split": "development",
            "used_for_tuning": True,
            "candidate_id": "source_a_g1_manipulation",
            "controller_version": source_contract["commit"],
            "engine": f"mujoco-{versions['mujoco']}",
            "seed": seed,
            "case_index": episode_index,
            "head_rgbd_status": "not_recorded_s2_component_smoke",
            "wrist_rgbd_status": "not_recorded_s2_component_smoke",
        },
    )
    instruction = TaskInstruction(
        task_type="pick_carry_stop_place_release_retreat",
        target_object_semantic_id="red_light_cylinder",
        target_support_semantic_id="blue_target_table",
        target_region_semantic_id="clear_tabletop_region",
        natural_language="Pick up the light red object and place it on the blue table.",
    )
    if state_capture is not None:
        state_capture.action_index = lambda: len(writer.policy_records) - 1
    counters = NativeCounters(
        mujoco,
        ort,
        max_physics_steps,
        max_sim_seconds,
        on_step=None if state_capture is None else state_capture.on_step,
    )
    adapter = SourceANativeParityAdapter(
        writer,
        instruction,
        pipeline.PICK_STANCE,
        pipeline.PLACE_STANCE,
        time_provider=lambda: 0.0 if counters._data is None else float(counters._data.time),
    )
    pipeline.COMMANDER = adapter
    result: dict[str, Any] = {}
    error = None
    overlay_report = None
    if runtime_overlay is not None:
        runtime_overlay.install(pipeline, sim)
    if phase_trace is not None:
        phase_trace.install(pipeline)
    counters.install()
    try:
        result = pipeline.run_once(
            **kwargs,
            video=None,
            snapshots=False,
            sim_limit=max_sim_seconds,
            wall_limit=850.0,
        )
    except BaseException:
        error = traceback.format_exc()
    finally:
        metrics = counters.close()
        pipeline.COMMANDER = None
        if phase_trace is not None:
            phase_trace.restore(pipeline)
        if runtime_overlay is not None:
            overlay_report = runtime_overlay.report()
            runtime_overlay.uninstall()

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
    policy_replay = read_policy_episode(output_dir / "episode_contract")
    privileged_replay = read_privileged_episode(output_dir / "episode_contract", explicit=True)
    contract_replay_passed = bool(
        len(policy_replay) == len(privileged_replay) == 2
        and [row["decision_index"] for row in policy_replay] == [0, 1]
        and [row["decision_index"] for row in privileged_replay] == [0, 1]
        and not any("source_a_command_context" in str(row) for row in policy_replay)
    )

    baseline_fields = parity_fields(
        baseline_report["source_result"], baseline_report["audit_metrics"]
    )
    adapted_fields = parity_fields(result, metrics)
    parity_checks = {
        key: equivalent(baseline_fields[key], adapted_fields[key]) for key in baseline_fields
    }
    native_parity_passed = bool(
        not error
        and result.get("success")
        and all(parity_checks.values())
        and contract_replay_passed
    )
    report = {
        "schema": "embodied-s2-adapter-smoke-result/v1",
        "candidate_id": "source_a_g1_manipulation",
        "adapter_smoke_passed": native_parity_passed,
        "native_parity_passed": native_parity_passed,
        "parity_checks": parity_checks,
        "baseline_fields": baseline_fields,
        "adapted_fields": adapted_fields,
        "contract_replay_passed": contract_replay_passed,
        "contract_manifest": contract_manifest,
        "source_result": json_safe(result),
        "audit_metrics": metrics,
        "runtime_overlay": overlay_report,
        "error": error,
        "wall_seconds": time.monotonic() - started,
        "render_passes": 0,
        "training_updates": 0,
        "manual_interventions": 0,
        "production_accepted": False,
        "learning_validated": False,
        "quality_boundary": (
            "S2 proves adapter parity and dual-layer write/replay only; the inherited "
            "penetration/clearance issues remain S3 quality risks."
        ),
    }
    write_json_atomic(output_dir / "RESULT.json", report)
    return report


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
    parser.add_argument("--max-physics-steps", type=int, default=120000)
    parser.add_argument("--max-sim-seconds", type=float, default=300.0)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        result = run_attempt(
            args.output_dir,
            args.source_a_run,
            args.baseline_result,
            args.seed,
            args.episode_index,
            args.max_physics_steps,
            args.max_sim_seconds,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "RUNNER_FAILURE.json",
            {
                "schema": "embodied-s2-runner-failure/v1",
                "error": error,
                "production_accepted": False,
            },
        )
        print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "adapter_smoke_passed": result["adapter_smoke_passed"],
                "physics_steps": result["audit_metrics"]["physics_steps"],
                "policy_forwards": result["audit_metrics"]["policy_forwards"],
            },
            sort_keys=True,
        )
    )
    return 0 if result["adapter_smoke_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
