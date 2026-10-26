"""Bind ordered stages to the exact preloaded grasp and audited predecessor."""

import argparse
from pathlib import Path
from .protocol import authorize
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def create(root, mode, output, standing_report=None):
    authorize(root)
    if output.exists():
        raise FileExistsError(output)
    protocol = read_bound_json(root / "PROTOCOL.json")
    prior = Path(protocol["prior_root"])
    candidate = read_bound_json(Path(protocol["prior_grasp_preflight"]["path"]))[
        "candidates"
    ][protocol["grasp_candidate_index"]]
    scene_path = Path(protocol["model_manifest"]["path"])
    scene = read_bound_json(scene_path)
    case = read_bound_json(prior / "matrix_protocol_01/C001.json")
    case.update(
        schema="ordered-preloaded-carry-case/v2",
        main_root=str(prior),
        protocol_root=str(root),
        protocol=_file_binding(root / "PROTOCOL.json"),
        model_path=scene["model"]["path"],
        scene_manifest_path=str(scene_path),
        scene_manifest=_file_binding(scene_path),
        carry_mode=mode,
        joint_noise_std_rad=0.0,
        grip_protocol=protocol["grip_protocol"],
        preloaded_grasp_not_pickup=True,
        grasp_candidate_index=protocol["grasp_candidate_index"],
        **{
            key: candidate[key]
            for key in (
                "payload_local_xyz_m",
                "initial_right_hand_targets",
                "right_hand_targets",
            )
        }
    )
    if mode == "walking":
        if standing_report is None:
            raise ValueError("independently accepted standing predecessor required")
        audit_path = standing_report.with_name("CARRY_AUDIT.json")
        report = read_bound_json(standing_report)
        audit = read_bound_json(audit_path)
        if (
            not audit["passed"]
            or not report["carrying_acceptance"]["passed"]
            or report["active_control_ticks"] != protocol["standing_full_ticks"]
        ):
            raise ValueError("six-second unsupported standing not accepted")
        case.update(
            standing_report=str(standing_report),
            standing_audit=str(audit_path),
            standing_report_binding=_file_binding(standing_report),
            standing_audit_binding=_file_binding(audit_path),
        )
    case.pop("content_sha256_excluding_this_field", None)
    case["content_sha256_excluding_this_field"] = canonical_sha256(case)
    write_json_atomic(output, case)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--mode", choices=("standing", "walking"), required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--standing-report", type=Path)
    a = p.parse_args()
    create(a.root, a.mode, a.output, a.standing_report)
