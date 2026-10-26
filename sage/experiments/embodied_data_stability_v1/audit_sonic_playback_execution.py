"""Audit a playing-reference smoke, including every active PD torque update."""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .audit_candidates import canonical_sha256, write_json_atomic
from .audit_sonic_supported_execution import audit_execution, read_bound_json
from . import sonic_native_dynamic_shadow as native
from .sonic_native_dynamic_shadow import official_control_arrays
from .sonic_native_planner_preflight import _file_binding
from .sonic_semantic_shadow import DEFAULT_ANGLES
from .sonic_shadow import SONIC_BODY_JOINT_ORDER


def audit_playback(root: Path) -> dict:
    import numpy as np

    baseline_audit = audit_execution(root)
    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    active = [
        row for row in trace["records"] if row["sonic_candidate_consumed_by_physics"]
    ]
    controls = {
        key: np.asarray(value) for key, value in official_control_arrays().items()
    }
    max_pd_error = 0.0
    no_bias = True
    target_unchanged = True
    actual_history_matches = True
    active_samples = [sample for row in active for sample in row["substeps"]]
    release = report["support"].get("release_on_active", False)
    maximum_active_support_wrench = max(
        (float(np.max(np.abs(sample["support_wrench"]))) for sample in active_samples),
        default=0.0,
    )
    no_active_support = (
        len(active_samples) == 400
        and maximum_active_support_wrench == 0.0
        and all(sample.get("support_enabled") is False for sample in active_samples)
    )
    for row in active:
        actual_history_matches &= (
            row["actual_command_raw_equivalent_isaaclab"] == row["raw_action_isaaclab"]
        )
        for sample in row["substeps"]:
            target_unchanged &= sample["position_target_rad"] == row["candidate_rad"]
            no_bias &= sample["bias_feedforward_used"] is False
            expected = np.clip(
                controls["kp"]
                * (
                    np.asarray(sample["position_target_rad"])
                    - sample["body_position_before_rad"]
                )
                - controls["kd"] * sample["body_velocity_before_rad_s"],
                -controls["effort_limit"],
                controls["effort_limit"],
            )
            max_pd_error = max(
                max_pd_error, float(np.max(np.abs(expected - sample["body_torque_nm"])))
            )
    reference = np.asarray([row["reference_qpos"] for row in active])
    actual = np.asarray([row["actual_qpos"] for row in active])
    samples = [sample for row in trace["records"] for sample in row["substeps"]]
    samples += trace["warmup_substeps"]
    numeric_physical_gates = all(
        np.isfinite(
            [
                sample["pelvis_height_m"],
                sample["up_component"],
                sample["penetration_m"],
                sample["contact_force_n"],
            ]
        ).all()
        and sample["pelvis_height_m"] >= native.MIN_PELVIS_HEIGHT_M
        and sample["up_component"] >= native.MIN_PELVIS_UP_COMPONENT
        and sample["penetration_m"] <= native.MAX_PENETRATION_M
        and sample["contact_force_n"] <= native.MAX_CONTACT_FORCE_N
        for sample in samples
    )
    model_xml = ET.parse(Path(report["source_bindings"]["model"]["path"])).getroot()
    ranges = {
        node.attrib["name"]: tuple(float(x) for x in node.attrib["range"].split())
        for node in model_xml.findall(".//joint")
        if "range" in node.attrib
    }
    lower = np.asarray([ranges[name][0] for name in SONIC_BODY_JOINT_ORDER])
    upper = np.asarray([ranges[name][1] for name in SONIC_BODY_JOINT_ORDER])
    commands_recomputed_safe = True
    previous = np.asarray(DEFAULT_ANGLES)
    for row in trace["records"]:
        candidate = np.asarray(row["candidate_rad"])
        computed_safe = (
            np.isfinite(candidate).all()
            and np.all((candidate >= lower) & (candidate <= upper))
            and np.max(np.abs(candidate - previous)) <= native.MAX_CANDIDATE_STEP_RAD
        )
        commands_recomputed_safe &= bool(computed_safe)
        previous = candidate
    metrics = {
        **baseline_audit["metrics"],
        "maximum_pd_error_all_active_substeps_nm": max_pd_error,
        "maximum_active_support_wrench_abs": maximum_active_support_wrench,
        "reference_maximum_joint_excursion_rad": (
            float(np.max(np.ptp(reference[:, 7:], axis=0))) if active else 0.0
        ),
        "reference_to_actual_joint_rmse_rad": (
            float(np.sqrt(np.mean((reference[:, 7:] - actual) ** 2)))
            if active
            else None
        ),
        "reference_to_actual_joint_maximum_error_rad": (
            float(np.max(np.abs(reference[:, 7:] - actual))) if active else None
        ),
        "actual_horizontal_net_displacement_m": report["motion_metrics"][
            "actual_horizontal_net_displacement_m"
        ],
        "reference_horizontal_net_displacement_m": report["motion_metrics"][
            "reference_horizontal_net_displacement_m"
        ],
    }
    gates = {
        **baseline_audit["gates"],
        "playing_reference_schema": report["schema"] == "sonic-playing-active-smoke/v1",
        "reference_playing": report["reference_playing"] is True,
        "reference_has_joint_motion": metrics["reference_maximum_joint_excursion_rad"]
        > 0.0,
        "all_400_pd_updates_exact": max_pd_error == 0.0,
        "no_active_model_bias_feedforward": no_bias,
        "raw_candidates_unchanged_in_every_pd_step": target_unchanged,
        "active_history_is_real_sonic_command": actual_history_matches,
        "numeric_physical_gates_recomputed": bool(numeric_physical_gates),
        "command_range_and_slew_recomputed": bool(commands_recomputed_safe),
        "active_support_schedule_matches": (
            no_active_support
            if release
            else all(
                sample.get("support_enabled", True) is True for sample in active_samples
            )
        ),
    }
    audit = {
        "schema": "sonic-playing-execution-audit/v1",
        "classification": "passed" if all(gates.values()) else "failed",
        "report": baseline_audit["report"],
        "trace": baseline_audit["trace"],
        "implementation": _file_binding(Path(__file__)),
        "base_auditor": _file_binding(
            Path(__file__).with_name("audit_sonic_supported_execution.py")
        ),
        "gates": gates,
        "metrics": metrics,
        "limits": {
            "support_remained_enabled": not release,
            "horizontal_support_constrains_translation": not release,
            "free_standing_validated": bool(
                release and no_active_support and all(gates.values())
            ),
            "free_standing_validation_duration_s": (
                2.0 if release and no_active_support and all(gates.values()) else 0.0
            ),
            "walking_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "full_mesh_collision_validated": False,
        },
        "physics_executed_by_auditor": False,
    }
    audit["content_sha256_excluding_this_field"] = canonical_sha256(audit)
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("audit output already exists")
    audit = audit_playback(args.run_root)
    write_json_atomic(args.output, audit)
    print(json.dumps(audit, indent=2))
    return 0 if audit["classification"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
