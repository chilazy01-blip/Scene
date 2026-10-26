"""Stop audit plus a causal event boundary against frozen successful walking."""

import argparse
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .audit_sonic_stop_execution import audit_stop
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_planner_preflight import _file_binding


def audit(root, walking_root):
    result = audit_stop(root)
    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    prior_report = read_bound_json(walking_root / "REPORT.json")
    prior_path = Path(prior_report["trace"]["path"])
    if sha256_file(prior_path) != prior_report["trace"]["sha256"]:
        raise ValueError("walking trace changed")
    prior = read_bound_json(prior_path)
    old = [r for r in prior["records"] if r["sonic_candidate_consumed_by_physics"]]
    active = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    keys = (
        "candidate_rad",
        "encoder_input_sha256",
        "decoder_input_sha256",
        "actual_qpos",
        "actual_qvel",
        "actual_quaternion",
        "actual_root_xyz_before_m",
    )
    result["gates"].update(
        {
            "stop_schema": report["schema"] == "sonic-reactive-stop-active-smoke/v1",
            "no_pre_event_stop_information_in_inputs_or_physics": len(active) >= 40
            and all(a[k] == b[k] for a, b in zip(active[:40], old[:40]) for k in keys),
            "stop_event_flags_exact": all(
                r["stop_event_received"]
                == (
                    r["sonic_candidate_consumed_by_physics"]
                    and r["reference_tick"] >= 40
                )
                for r in trace["records"]
                if r["substeps"]
            ),
            "event_protocol_declared": report["planner"].get("stop_preview_protocol")
            == "event_causal_not_announced_before_tick40",
            "walking_comparison_already_validated": prior_report["walking_acceptance"][
                "passed"
            ]
            is True,
        }
    )
    result["schema"] = "sonic-reactive-stop-audit/v1"
    result["walking_comparison_report"] = _file_binding(walking_root / "REPORT.json")
    result["walking_comparison_trace"] = _file_binding(prior_path)
    result["implementation"] = _file_binding(Path(__file__))
    result["dependencies"]["audit_sonic_stop_execution"] = _file_binding(
        Path(__file__).with_name("audit_sonic_stop_execution.py")
    )
    accepted = all(result["gates"].values())
    result["classification"] = "passed" if accepted else "not_accepted"
    result["controlled_stop_validated"] = accepted
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
    print(json.dumps(result, indent=2))
    return 0 if result["controlled_stop_validated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
