"""Independent stop/hold audit; incomplete or rejected runs remain not_accepted."""

import argparse
import json
from pathlib import Path

from .audit_candidates import canonical_sha256, write_json_atomic
from .audit_sonic_playback_execution import audit_playback
from .audit_sonic_supported_execution import read_bound_json
from .audit_sonic_walking_execution import recount_steps
from .sonic_native_planner_preflight import _file_binding


def audit_stop(root):
    import numpy as np

    base = audit_playback(root)
    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    active = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    samples = [s for r in active for s in r["substeps"]]
    tail = samples[-100:]
    # Independent numeric reduction, not a call to the engine's stop metrics.
    velocity = np.asarray([s["root_velocity_after_m_s"][:2] for s in tail])
    locations = np.asarray(
        [tail[0]["full_qpos_before"][:2], *[s["full_qpos_after"][:2] for s in tail]]
    )
    speed = float(np.max(np.linalg.norm(velocity, axis=1)))
    drift = float(np.max(np.linalg.norm(locations - locations[0], axis=1)))
    joint_rms = float(
        np.max(
            np.sqrt(
                np.mean(
                    np.square([s["body_velocity_after_rad_s"] for s in tail]), axis=1
                )
            )
        )
    )
    both = float(
        np.mean(
            [
                min(
                    s["feet"][side]["ground_contact_force_max_n"]
                    for side in ("left", "right")
                )
                > 2
                for s in tail
            ]
        )
    )
    cycles = {side: recount_steps(samples, side) for side in ("left", "right")}
    forward = (
        active[-1]["actual_root_xyz_after_m"][0]
        - active[0]["actual_root_xyz_before_m"][0]
    )
    limits = {
        "hold_substeps": 100,
        "max_horizontal_speed_m_s": 0.08,
        "max_horizontal_drift_m": 0.02,
        "max_joint_velocity_rms_rad_s": 0.6,
        "min_both_feet_contact_fraction": 0.9,
        "min_forward_displacement_m": 0.05,
        "min_completed_footstep_cycles_total": 1,
    }
    metrics = {
        "hold_max_horizontal_speed_m_s": speed,
        "hold_horizontal_drift_m": drift,
        "hold_max_joint_velocity_rms_rad_s": joint_rms,
        "hold_both_feet_contact_fraction": both,
        "forward_displacement_m": forward,
        "completed_cycles": cycles,
    }
    gates = {k: v for k, v in base["gates"].items() if k != "playing_reference_schema"}
    gates.update(
        {
            "stop_schema": report["schema"]
            in (
                "sonic-walk-stop-active-smoke/v1",
                "sonic-walk-early-stop-active-smoke/v1",
                "sonic-walk-mid-stop-active-smoke/v1",
            ),
            "thresholds_frozen": report["controlled_stop_acceptance"]["thresholds"]
            == limits,
            "recorded_metrics_match": report["controlled_stop_acceptance"]["metrics"]
            == metrics,
            "exact_reference_clock": all(
                r["reference_tick"] == 0 for r in trace["records"][:50]
            )
            and [r["reference_tick"] for r in active] == list(range(100)),
            "planned_idle_command": report["planner"].get("stop_mode") == 0
            and report["planner"].get("stop_command_frame") in (20, 30, 40),
            "genuine_step_and_progress": forward >= 0.05 and sum(cycles.values()) >= 1,
            "hold_speed": speed <= 0.08,
            "hold_drift": drift <= 0.02,
            "hold_joint_velocity": joint_rms <= 0.6,
            "hold_both_feet_contact": both >= 0.9,
            "state_chain_exact": all(
                samples[i]["full_qpos_after"] == samples[i + 1]["full_qpos_before"]
                for i in range(len(samples) - 1)
            ),
        }
    )
    result = {
        "schema": "sonic-stop-execution-audit/v1",
        "classification": "passed" if all(gates.values()) else "not_accepted",
        "report": base["report"],
        "trace": base["trace"],
        "implementation": _file_binding(Path(__file__)),
        "dependencies": {
            n: _file_binding(Path(__file__).with_name(n + ".py"))
            for n in (
                "audit_sonic_playback_execution",
                "audit_sonic_supported_execution",
                "audit_sonic_walking_execution",
            )
        },
        "gates": gates,
        "metrics": {**base["metrics"], **metrics},
        "controlled_stop_validated": all(gates.values()),
        "physics_executed_by_auditor": False,
        "production_accepted": False,
        "batch_authorized": False,
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
    result = audit_stop(args.run_root)
    write_json_atomic(args.output, result)
    print(json.dumps(result, indent=2))
    return 0 if result["controlled_stop_validated"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
