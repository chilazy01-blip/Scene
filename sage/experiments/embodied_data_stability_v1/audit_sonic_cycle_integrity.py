"""Rebuild every reference input and prove no braking intent leaked earlier."""

import argparse
import hashlib
import json
from pathlib import Path

from . import sonic_native_dynamic_shadow as native
from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .audit_sonic_supported_execution import read_bound_json
from .sonic_native_full_shadow import _make_session
from .sonic_native_planner_preflight import _file_binding
from .sonic_phase_braking_reference import build_braking_reference, select_reference
from .sonic_semantic_shadow import ENCODER_ASSEMBLER


def audit(root, walking_root):
    import numpy as np

    report = read_bound_json(root / "REPORT.json")
    trace = read_bound_json(Path(report["trace"]["path"]))
    primary = read_bound_json(root / "INDEPENDENT_AUDIT.json")
    walking = read_bound_json(walking_root / "REPORT.json")
    old_trace_path = Path(walking["trace"]["path"])
    if sha256_file(old_trace_path) != walking["trace"]["sha256"]:
        raise ValueError("walking comparison trace changed")
    old = read_bound_json(old_trace_path)
    planner = _make_session(Path(report["inputs"]["planner"]["path"]))
    settings = report["planner"]
    versions, metadata = build_braking_reference(
        planner,
        brake_frame=settings["brake_command_frame"],
        brake_speed=settings["brake_speed_m_s"],
        idle_frame=settings["stop_command_frame"],
        total_frames=350,
    )
    del planner
    failures = []
    for row in trace["records"]:
        q, v = select_reference(versions, row["reference_tick"])
        values = ENCODER_ASSEMBLER.assemble(
            native.build_dynamic_g1_encoder_blocks(
                q,
                v,
                row["reference_tick"],
                initial_robot_quaternion_wxyz=(1.0, 0.0, 0.0, 0.0),
                current_robot_quaternion_wxyz=row["actual_quaternion"],
            )
        )
        digest = hashlib.sha256(
            np.asarray([values], dtype=np.float32).tobytes()
        ).hexdigest()
        if digest != row["encoder_input_sha256"]:
            failures.append(row["tick"])
    active = [r for r in trace["records"] if r["sonic_candidate_consumed_by_physics"]]
    prior = [r for r in old["records"] if r["sonic_candidate_consumed_by_physics"]]
    keys = (
        "candidate_rad",
        "encoder_input_sha256",
        "decoder_input_sha256",
        "actual_qpos",
        "actual_qvel",
        "actual_quaternion",
        "actual_root_xyz_before_m",
    )
    n = settings["brake_command_frame"]
    gates = {
        "primary_independent_audit_passed": primary["task_passed"] is True,
        "reference_versions_reproduced_exactly": metadata["version_hashes"]
        == settings["version_hashes"],
        "all_encoder_reference_inputs_rebuilt_exactly": not failures,
        "pre_braking_real_state_input_candidate_matches_successful_walking": len(active)
        >= n
        and len(prior) >= n
        and all(a[k] == b[k] for a, b in zip(active[:n], prior[:n]) for k in keys),
        "measured_render_pose_equals_recorded_physics_pose": all(
            [*r["actual_root_xyz_before_m"], *r["actual_quaternion"], *r["actual_qpos"]]
            == r["substeps"][0]["full_qpos_before"]
            for r in active
        ),
        "final_stationary_target_has_zero_velocity": not np.any(
            versions[-1][2][settings["stop_command_frame"] :]
        ),
        "final_reference_joint_pose_is_official_idle": np.array_equal(
            versions[-1][1][-1, 7:], versions[0][1][0, 7:]
        ),
    }
    result = {
        "schema": "sonic-motion-cycle-integrity-audit/v1",
        "classification": "passed" if all(gates.values()) else "failed",
        "gates": gates,
        "encoder_mismatch_ticks": failures,
        "pre_braking_ticks_compared": n,
        "reconstructed_encoder_inputs": len(trace["records"]),
        "physics_steps": 0,
        "implementation": _file_binding(Path(__file__)),
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "primary_audit": _file_binding(root / "INDEPENDENT_AUDIT.json"),
        "walking_report": _file_binding(walking_root / "REPORT.json"),
        "walking_trace": _file_binding(old_trace_path),
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    return result


if __name__ == "__main__":
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
            {"classification": result["classification"], "gates": result["gates"]},
            indent=2,
        )
    )
