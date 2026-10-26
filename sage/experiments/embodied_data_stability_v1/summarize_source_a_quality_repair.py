"""Bind the frozen S3 baseline and two bounded repair attempts into one report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import write_json_atomic
from .run_source_a_native import sha256_file


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _category(result: dict[str, Any], name: str) -> dict[str, Any]:
    return result.get("metrics", {}).get("contact_categories", {}).get(name, {})


def build_comparison(
    baseline_path: Path,
    v1_path: Path,
    v2_path: Path,
) -> dict[str, Any]:
    baseline = _load(baseline_path)
    v1 = _load(v1_path)
    v2 = _load(v2_path)

    def bound(path: Path) -> dict[str, Any]:
        return {"path": str(path), "sha256": sha256_file(path)}

    return {
        "schema": "embodied-source-a-quality-repair-comparison/v1",
        "same_case": {
            "seed": 3,
            "episode_index": 0,
            "baseline": bound(baseline_path),
            "first_contact_only_v1": bound(v1_path),
            "cage_depth_v2": bound(v2_path),
        },
        "outcomes": {
            "frozen_s3": {
                "task_success": baseline["end_to_end_task_passed"],
                "classification": baseline["classification"],
                "global_max_penetration_m": baseline["metrics"]["max_penetration_m"],
                "hand_object_peak_m": baseline["metrics"]["max_penetration_m"],
                "hand_object_peak_source": "S3 peak-pair audit: red cylinder/right thumb2",
                "carry_clearance_m": baseline["metrics"]["min_carry_clearance_m"],
                "lift_rise_m": 0.1423,
            },
            "repair_v1": {
                "task_success": v1["end_to_end_task_passed"],
                "classification_as_written": v1["classification"],
                "classification_note": (
                    "The run was data-intact but the first runner reused S2's exactly-two-"
                    "decision parity assertion after an early pick failure. V2 corrected the "
                    "repair-run classifier; the preserved V1 JSON is not rewritten."
                ),
                "global_max_penetration_m": v1["metrics"]["max_penetration_m"],
                "hand_object_peak_m": _category(v1, "hand_object").get("max_penetration_m"),
                "close_depth_delta_m": -0.0007,
                "lift_rise_m": -0.0176,
            },
            "repair_v2": {
                "task_success": v2["end_to_end_task_passed"],
                "classification": v2["classification"],
                "audit_data_complete": v2["audit_data_complete"],
                "global_max_penetration_m": v2["metrics"]["max_penetration_m"],
                "hand_object_peak_m": _category(v2, "hand_object").get("max_penetration_m"),
                "foot_ground_peak_m": _category(v2, "foot_ground").get("max_penetration_m"),
                "object_source_table_peak_m": _category(v2, "object_source_table").get(
                    "max_penetration_m"
                ),
                "close_depth_delta_m": -0.0013,
                "lift_rise_m": -0.0163,
                "path_and_release_exercised": False,
            },
        },
        "causal_read": {
            "supported": [
                "Independent contact latching reduced hand-object penetration below the "
                "10 mm gate in both repair attempts.",
                "First contact plus at most 40 mrad bounded preload did not move the object "
                "into the 3--4.5 cm in-palm cage before lift.",
                "The frozen successful grasp moved the object 12.1 mm into the palm during "
                "squeeze; V1 and V2 moved it only 0.7 mm and 1.3 mm.",
                "The 12.97 mm foot-ground transient is independent of the hand controller.",
            ],
            "not_tested": [
                "geometry-aware untuck/pre-place routing",
                "support-confirmed staged release",
            ],
            "rejected": [
                "source_a_contact_clearance_repair_v1",
                "source_a_contact_clearance_repair_v2",
            ],
        },
        "exit": {
            "bounded_smoke_budget_used": 2,
            "bounded_smoke_budget_limit": 2,
            "run_more_automatically": False,
            "production_accepted": False,
            "learning_validated": False,
            "long_run_authorized": False,
            "next_required_evidence": (
                "A zero/low-physics grasp-geometry study must find a pregrasp or closure "
                "trajectory that forms an opposing cage without exceeding the 8 mm guard. "
                "Do not continue a scalar preload sweep."
            ),
        },
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--v1", type=Path, required=True)
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    write_json_atomic(args.output, build_comparison(args.baseline, args.v1, args.v2))
    print(json.dumps({"output": str(args.output), "written": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
