"""Independent full-state/command/footstep acceptance of a SONIC walking run."""

from __future__ import annotations

import argparse
import json
from itertools import groupby
from pathlib import Path

from .audit_candidates import canonical_sha256, write_json_atomic
from .audit_sonic_playback_execution import audit_playback
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_planner_preflight import _file_binding


def recount_steps(samples, side):
    labels = []
    for sample in samples:
        foot = sample["feet"][side]
        if foot["ground_contact_force_max_n"] > 2.0:
            labels.append("stance")
        elif foot["sole_clearance_m"] >= 0.010:
            labels.append("swing")
    sequence = [key for key, _ in groupby(labels)]
    return sum(
        sequence[i : i + 3] == ["stance", "swing", "stance"]
        for i in range(max(0, len(sequence) - 2))
    )


def audit_walking(root):
    import numpy as np

    base = audit_playback(root)
    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    active = [
        row for row in trace["records"] if row["sonic_candidate_consumed_by_physics"]
    ]
    samples = [sample for row in active for sample in row["substeps"]]
    cycles = {side: recount_steps(samples, side) for side in ("left", "right")}
    forward = (
        float(
            active[-1]["actual_root_xyz_after_m"][0]
            - active[0]["actual_root_xyz_before_m"][0]
        )
        if active
        else 0.0
    )
    gates = {
        key: value
        for key, value in base["gates"].items()
        if key != "playing_reference_schema"
    }
    gates.update(
        {
            "walking_reference_schema": report["schema"]
            in (
                "sonic-walk-active-smoke/v1",
                "sonic-slow-walk-active-smoke/v1",
                "sonic-slow-walk-paced-active-smoke/v1",
            ),
            "standing_preview_clock_and_exact_active_phase": all(
                row["reference_tick"] == 0 for row in trace["records"][:50]
            )
            and [row["reference_tick"] for row in active] == list(range(100)),
            "forward_progress_at_least_50mm": forward >= 0.05,
            "each_foot_completed_stance_swing_stance": all(
                count >= 1 for count in cycles.values()
            ),
            "acceptance_limits_unchanged": report["walking_acceptance"]["thresholds"]
            == {
                "min_forward_displacement_m": 0.05,
                "swing_clearance_m": 0.01,
                "stance_contact_force_n": 2.0,
                "minimum_cycles_each_foot": 1,
            },
            "engine_footstep_counts_match_independent_recount": cycles
            == report["walking_acceptance"]["completed_stance_swing_stance_cycles"],
        }
    )
    result = {
        "schema": "sonic-walking-execution-audit/v1",
        "classification": "passed" if all(gates.values()) else "not_accepted",
        "report": base["report"],
        "trace": base["trace"],
        "implementation": _file_binding(Path(__file__)),
        "base_auditor": _file_binding(
            Path(__file__).with_name("audit_sonic_playback_execution.py")
        ),
        "gates": gates,
        "metrics": {
            **base["metrics"],
            "actual_forward_displacement_m": forward,
            "completed_cycles_each_foot": cycles,
            "maximum_sole_clearance_m": {
                side: max(
                    (sample["feet"][side]["sole_clearance_m"] for sample in samples),
                    default=0.0,
                )
                for side in cycles
            },
            "initial_body_xy_m": (
                active[0]["actual_root_xyz_before_m"][:2] if active else None
            ),
            "final_body_xy_m": (
                active[-1]["actual_root_xyz_after_m"][:2] if active else None
            ),
        },
        "capability_boundary": {
            "walking_validated": all(gates.values()),
            "validation_duration_s": 2.0 if all(gates.values()) else 0.0,
            "long_duration_or_generalization_validated": False,
            "full_mesh_collision_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
        "physics_executed_by_auditor": False,
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit_walking(args.run_root)
    write_json_atomic(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["classification"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
