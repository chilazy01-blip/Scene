"""Reconstruct all actual reference inputs and independently recount goal events."""

import argparse
import hashlib
from pathlib import Path
import numpy as np

from .reference import walking, brake
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)


def audit_run(root, gait, velocity):
    report = read_bound_json(root / "REPORT.json")
    case = report["case_config"]
    trace = read_bound_json(Path(report["trace"]["path"]))
    event = None
    reference = gait
    v = velocity
    mismatch = []
    event_mismatch = []
    yaw = case["start_yaw_rad"]
    direction = np.array([np.cos(yaw), np.sin(yaw)])
    initial = [np.cos(yaw / 2), 0, 0, np.sin(yaw / 2)]
    for row in trace["records"]:
        frame = row["reference_tick"]
        if row["sonic_candidate_consumed_by_physics"]:
            progress = float(
                (np.array(row["actual_root_xyz_before_m"][:2]) - case["start_xy_m"])
                @ direction
            )
            if (
                event is None
                and frame >= 75
                and progress >= case["goal_distance_m"] - 0.16
            ):
                event = frame
                reference, v, _ = brake(gait, velocity, event)
        if row["goal_brake_frame"] != event:
            event_mismatch.append(row["tick"])
        values = ENCODER_ASSEMBLER.assemble(
            native.build_dynamic_g1_encoder_blocks(
                reference,
                v,
                frame,
                initial_robot_quaternion_wxyz=initial,
                current_robot_quaternion_wxyz=row["actual_quaternion"],
            )
        )
        digest = hashlib.sha256(
            np.asarray([values], dtype=np.float32).tobytes()
        ).hexdigest()
        if digest != row["encoder_input_sha256"]:
            mismatch.append(row["tick"])
    result = {
        "schema": "goal-triggered-reference-integrity/v1",
        "passed": not mismatch and not event_mismatch,
        "encoder_mismatch_ticks": mismatch,
        "goal_event_mismatch_ticks": event_mismatch,
        "independently_recounted_brake_frame": event,
        "reported_brake_frame": report["planner"]["brake_command_frame"],
        "reconstructed_inputs": len(trace["records"]),
        "report": _file_binding(root / "REPORT.json"),
        "trace": report["trace"],
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
    }
    result["passed"] &= event == report["planner"]["brake_command_frame"]
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    return result


def matrix(root):
    planner = _make_session(
        native.DEFAULT_BUNDLE / "planner/target_vel/V2/planner_sonic.onnx"
    )
    gait, velocity, _ = walking(planner)
    del planner
    cases = read_bound_json(root / "matrix_protocol_01/MATRIX.json")["cases"]
    results = []
    for item in cases:
        directory = root / "matrix_run_01" / item["id"] / "full"
        if not (directory / "REPORT.json").exists():
            continue
        output = directory / "REFERENCE_AUDIT.json"
        if output.exists():
            raise FileExistsError(output)
        result = audit_run(directory, gait, velocity)
        write_json_atomic(output, result)
        results.append(_file_binding(output))
        print(
            item["id"],
            "reference",
            result["passed"],
            "brake",
            result["reported_brake_frame"],
            flush=True,
        )
    document = {
        "schema": "matrix-reference-integrity/v1",
        "cases": results,
        "passed": all(read_bound_json(Path(b["path"]))["passed"] for b in results),
        "implementation": _file_binding(Path(__file__)),
        "physics_steps": 0,
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    write_json_atomic(root / "matrix_run_01/REFERENCE_AUDIT.json", document)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    matrix(p.parse_args().root)
