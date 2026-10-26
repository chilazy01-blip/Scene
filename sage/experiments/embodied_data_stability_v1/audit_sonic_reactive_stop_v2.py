"""Clarify partial-run diagnostics and allow only floating-reduction roundoff.

No safety/stop threshold is changed. v1 output remains immutable evidence.
"""

import argparse
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, write_json_atomic
from .audit_sonic_reactive_stop import audit as audit_v1
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_planner_preflight import _file_binding


def audit(root, walking_root):
    import numpy as np

    result = audit_v1(root, walking_root)
    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    admitted = read_bound_json(Path(report["admission"]["path"]))
    prior = read_bound_json(Path(admitted["trace"]["path"]))
    keys = (
        "candidate_rad",
        "encoder_input_sha256",
        "decoder_input_sha256",
        "actual_qpos",
        "actual_qvel",
        "actual_quaternion",
        "actual_gyro",
    )
    gates = result["gates"]
    gates["exact_50_tick_real_state_prefix"] = len(trace["records"]) >= 50 and all(
        a[k] == b[k]
        for a, b in zip(trace["records"][:50], prior["records"][:50])
        for k in keys
    )
    gates["all_executed_pd_updates_exact"] = gates.pop("all_400_pd_updates_exact")
    samples = [
        s
        for r in trace["records"]
        if r["sonic_candidate_consumed_by_physics"]
        for s in r["substeps"]
    ]
    gates["active_support_schedule_matches"] = all(
        not s["support_enabled"] and not any(s["support_wrench"]) for s in samples
    )
    errors = []
    for name, value in report["controlled_stop_acceptance"]["metrics"].items():
        if isinstance(value, dict):
            errors.append(0.0 if value == result["metrics"][name] else float("inf"))
        else:
            errors.append(abs(value - result["metrics"][name]))
    gates["recorded_metrics_match"] = max(errors, default=0.0) <= 1e-12
    result["metrics"]["maximum_engine_independent_reduction_error"] = max(
        errors, default=0.0
    )
    result["metric_comparison_absolute_tolerance"] = 1e-12
    result["schema"] = "sonic-reactive-stop-audit/v2"
    result["implementation"] = _file_binding(Path(__file__))
    result["dependencies"]["audit_sonic_reactive_stop"] = _file_binding(
        Path(__file__).with_name("audit_sonic_reactive_stop.py")
    )
    result["controlled_stop_validated"] = all(gates.values())
    result["classification"] = "passed" if all(gates.values()) else "not_accepted"
    result.pop("content_sha256_excluding_this_field")
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--walking-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = audit(args.run_root, args.walking_root)
    write_json_atomic(args.output, result)
    print(
        json.dumps(
            {
                "classification": result["classification"],
                "gates": result["gates"],
                "reduction_error": result["metrics"][
                    "maximum_engine_independent_reduction_error"
                ],
            },
            indent=2,
        )
    )
    return 0 if result["controlled_stop_validated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
