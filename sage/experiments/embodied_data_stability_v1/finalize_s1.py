"""Bind S1 evidence and freeze the first expert/comparator/engine selection."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic


DEFAULT_S0_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s0_20261014_v1"
)
DEFAULT_S1_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s1_20261014_v1"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def evidence(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def build_report(s0_root: Path, s1_root: Path) -> dict[str, Any]:
    s0_gate_path = s0_root / "S0_GATE.json"
    source_path = s1_root / "source_a_native_01" / "RESULT.json"
    groot_preflight_failure = s1_root / "groot_decoupled_native_01" / "RUNNER_FAILURE.json"
    groot_path = s1_root / "groot_decoupled_native_02" / "RESULT.json"
    paths = [s0_gate_path, source_path, groot_preflight_failure, groot_path]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"missing S1 evidence: {missing}")
    s0_gate = read_object(s0_gate_path)
    source = read_object(source_path)
    groot_failure = read_object(groot_preflight_failure)
    groot = read_object(groot_path)
    checks = {
        "s0_passed": s0_gate.get("s0_exit_passed") is True,
        "source_a_native_full_task_passed": source.get("native_reproduction_passed") is True,
        "groot_decoupled_component_passed": groot.get("native_reproduction_passed") is True,
        "groot_first_attempt_failed_before_physics": (
            "unexpected balance ONNX interface" in groot_failure.get("error", "")
        ),
        "both_runs_unrendered": source.get("render_passes") == groot.get("render_passes") == 0,
        "both_runs_untrained": source.get("training_updates") == groot.get("training_updates") == 0,
        "no_manual_intervention": (
            source.get("manual_interventions") == groot.get("manual_interventions") == 0
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"S1 evidence checks failed: {checks}")

    source_metrics = source["audit_metrics"]
    groot_metrics = groot["metrics"]
    return {
        "schema": "embodied-data-stability-s1-selection/v1",
        "s1_exit_passed": True,
        "selection_frozen": True,
        "checks": checks,
        "selection": {
            "primary_expert": {
                "id": "source_a_g1_manipulation",
                "role": "complete pick-carry-stop-place teacher",
                "reason": (
                    "Only admitted candidate with an unmodified-weight, complete-task native "
                    "success and explicit pick/transport/place predicates."
                ),
                "distribution_status": "internal_only",
            },
            "backup_comparator": {
                "id": "groot_decoupled_wbc",
                "role": "standing/walking/stopping WBC shadow comparator",
                "reason": (
                    "Pinned upstream Balance/Walk weights passed the frozen component protocol."
                ),
                "not_selected_as": ["complete manipulation expert", "SONIC-v1.1 reproduction"],
                "distribution_status": "unresolved_internal_only",
            },
            "production_engine_candidate": {
                "engine": "MuJoCo",
                "version_for_s2_s3": source["runtime_versions"]["mujoco"],
                "reason": "The selected primary expert's native full task runs in this engine.",
                "note": (
                    "GR00T remains in its native MuJoCo 3.3.2 environment for shadow evidence; "
                    "its data is not mixed into the first production dataset."
                ),
            },
            "unitree_rl_lab": {
                "role": "deferred chassis comparator",
                "status": "s1_blocked",
                "blockers": ["Isaac Lab/Isaac Sim runtime absent", "external Unitree assets absent"],
            },
            "sonic_v1_1": {
                "status": "s1_blocked",
                "blockers": ["selected weights absent", "native build/runtime absent"],
            },
        },
        "observed_cost": {
            "source_a": {
                "sim_seconds": source["source_result"]["sim_time_s"],
                "runner_wall_seconds": source["wall_seconds"],
                "physics_steps": source_metrics["physics_steps"],
                "policy_forwards": source_metrics["policy_forwards"],
            },
            "groot_decoupled": {
                "sim_seconds": groot_metrics["sim_seconds"],
                "runner_wall_seconds": groot["wall_seconds"],
                "physics_steps": groot_metrics["physics_steps"],
                "policy_forwards": groot_metrics["policy_forwards"],
            },
            "rgbd_storage_per_episode": "unknown_not_measured",
        },
        "known_risks": [
            {
                "id": "source_a_penetration",
                "value_m": source_metrics["max_penetration_m"],
                "status": "must_be_gated_in_s2_s3",
            },
            {
                "id": "source_a_carry_clearance",
                "value_m": source["source_result"]["carry_clear_min_m"],
                "status": "negative_clearance_observed",
            },
            {
                "id": "single_success_not_stability",
                "status": "no_repeated_batch_claim",
            },
            {
                "id": "license_boundary",
                "status": "internal_evaluation_only",
            },
        ],
        "next_stage": {
            "stage": "S2",
            "action": (
                "Implement a controller-neutral mixed high-level action and dual-layer data "
                "contract, then run native-parity component smoke in the primary engine."
            ),
            "authorized_smoke_attempts_max": 3,
        },
        "evidence": [evidence(path) for path in paths],
        "production_accepted": False,
        "learning_validated": False,
        "long_run_authorized": False,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s0-root", type=Path, default=DEFAULT_S0_ROOT)
    parser.add_argument("--s1-root", type=Path, default=DEFAULT_S1_ROOT)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output or args.s1_root / "S1_SELECTION.json"
    try:
        report = build_report(args.s0_root, args.s1_root)
        write_json_atomic(output, report)
    except BaseException:
        print(traceback.format_exc(), file=sys.stderr)
        return 1
    print(json.dumps({"output": str(output), "s1_exit_passed": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
