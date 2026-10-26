"""Rebuild every encoder input causally from the initial gait and reference events."""

import argparse
import hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .task import Task, smooth
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
    write_json_atomic,
    sha256_file,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)


def audit(root):
    import mujoco

    output = root / "REFERENCE_AUDIT.json"
    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(root / "REPORT.json")
    for binding in [
        report["case"],
        report["trace"],
        report["model"],
        report["inputs"]["planner"],
        *report["source_bindings"].values(),
    ]:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("bound reference dependency changed")
    case = read_bound_json(Path(report["case"]["path"]))
    trace = read_bound_json(Path(report["trace"]["path"]))
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    planner = _make_session(Path(report["inputs"]["planner"]["path"]))
    task = Task(planner, case, model, mujoco)
    initial = np.array(trace["warmup_substeps"][0]["full_qpos_before"][3:7])
    events = trace["reference_events"]
    event_index = 0
    mismatches = []
    max_error = 0.0
    checks = 0
    snapshots = np.load(root / "reference_snapshots.npz")
    snapshot_match = True
    for index, row in enumerate(trace["records"]):
        frame = row["reference_tick"]
        if row["sonic_candidate_consumed_by_physics"]:
            while event_index < len(events) and events[event_index]["frame"] <= frame:
                e = events[event_index]
                event_index += 1
                f = e["frame"]
                kind = e["kind"]
                if kind == "brake":
                    task.brake(f)
                    if task.reference_events[-1]["target"] != e["target"]:
                        raise ValueError("brake target reconstruction differs")
                elif kind == "cartesian_arm_path":
                    knots = e["knots"]
                    offsets = np.array([x[0] for x in knots])
                    angles = np.array([x[1] for x in knots])
                    ages = np.arange(len(task.q) - f)
                    for j, col in enumerate(task.arm + 7):
                        task.q[f:, col] = np.interp(ages, offsets, angles[:, j])
                    task.v = native._reference_velocities(task.q)
                elif kind == "arm_goal":
                    task.arm_goal(f, e["angles_rad"], e["duration"])
                elif kind == "begin_carry_walk":
                    qpos = np.array(row["substeps"][0]["full_qpos_before"])
                    task.begin_carry(f, SimpleNamespace(qpos=qpos))
                    if task.reference_events[-1]["start_pose"] != e["start_pose"]:
                        raise ValueError("carry start reconstruction differs")
                elif kind != "grip_anchor":
                    raise ValueError("unknown reference event " + kind)
        values = ENCODER_ASSEMBLER.assemble(
            native.build_dynamic_g1_encoder_blocks(
                task.q,
                task.v,
                frame,
                initial_robot_quaternion_wxyz=initial,
                current_robot_quaternion_wxyz=np.array(row["actual_quaternion"]),
            )
        )
        expected = np.asarray([values], dtype=np.float32)
        digest = hashlib.sha256(expected.tobytes()).hexdigest()
        err = float(
            np.max(
                np.abs(
                    expected[0]
                    - np.array(row["encoder_input_values"], dtype=np.float32)
                )
            )
        )
        max_error = max(max_error, err)
        checks += 1
        if digest != row["encoder_input_sha256"]:
            mismatches.append({"tick": row["tick"], "frame": frame, "max_error": err})
        snapshot_match &= np.array_equal(
            task.q[frame], snapshots["per_tick_qpos"][index]
        )
    result = {
        "schema": "transport-causal-reference-audit/v1",
        "passed": not mismatches and snapshot_match,
        "checked_encoder_inputs": checks,
        "max_float32_error": max_error,
        "mismatches": mismatches,
        "per_tick_reference_equal": bool(snapshot_match),
        "physics_steps": 0,
        "report": _file_binding(root / "REPORT.json"),
        "implementation": _file_binding(Path(__file__)),
        "scope": "causal encoder/reference reconstruction; not task success or independent learned-policy inference",
    }
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    audit(p.parse_args().root)
