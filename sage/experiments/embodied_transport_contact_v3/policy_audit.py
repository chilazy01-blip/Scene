"""Independent causal reference, actual mixed history, encoder/decoder replay."""

import argparse
import hashlib
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .task import Task
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    official_decoder_blocks,
    last_action_rows,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ACTION_SCALES,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def audit(root):
    import mujoco

    output = root / "POLICY_AUDIT.json"
    if output.exists():
        raise FileExistsError(output)
    r = read_bound_json(root / "REPORT.json")
    for binding in [
        r["case"],
        r["trace"],
        r["model"],
        r["reference_snapshots"],
        *r["inputs"].values(),
        *r["source_bindings"].values(),
    ]:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("changed evidence: " + binding["path"])
    case = read_bound_json(Path(r["case"]["path"]))
    trace = read_bound_json(Path(r["trace"]["path"]))
    m = mujoco.MjModel.from_xml_path(case["model_path"])
    m.opt.timestep = 0.005
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    pelvis = m.body("pelvis").id
    task = Task(_make_session(Path(r["inputs"]["planner"]["path"])), case, m, mujoco)
    encoder = _make_session(Path(r["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(r["inputs"]["decoder"]["path"]))
    positions = []
    velocities = []
    quaternions = []
    gyros = []
    applied = np.zeros((len(trace["records"]) + 10, 29), dtype=np.float32)

    def history(sample):
        d.qpos[:] = sample["full_qpos_before"]
        d.qvel[:] = sample["full_qvel_before"]
        mujoco.mj_forward(m, d)
        positions.append(d.qpos[ids["qpos_ids"]].copy())
        velocities.append(d.qvel[ids["dof_ids"]].copy())
        quaternions.append(d.qpos[3:7].copy())
        gyro = np.zeros(6)
        mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, pelvis, gyro, 1)
        gyros.append(gyro[:3].copy())

    for tick in range(10):
        history(trace["warmup_substeps"][4 * tick])
        applied[tick] = reorder_mujoco_to_isaaclab(
            (task.q[0, 7:] - DEFAULT_ANGLES) / ACTION_SCALES
        )
    initial = np.array(trace["warmup_substeps"][0]["full_qpos_before"][3:7])
    events = trace["reference_events"]
    event_index = 0
    snapshots = np.load(root / "reference_snapshots.npz")
    mismatches = []
    max_encoder = max_raw = max_knots = 0.0
    knot_checks = 0
    reference_equal = True
    for index, row in enumerate(trace["records"]):
        frame = row["reference_tick"]
        history(row["substeps"][0])
        if row["sonic_candidate_consumed_by_physics"]:
            task.stage = row["task"]["stage"]
            while event_index < len(events) and events[event_index]["frame"] <= frame:
                e = events[event_index]
                event_index += 1
                f = e["frame"]
                kind = e["kind"]
                if kind == "brake":
                    task.brake(f)
                    if task.reference_events[-1]["target"] != e["target"]:
                        raise ValueError("brake replay differs")
                elif kind == "begin_carry_walk":
                    task.begin_carry(f, SimpleNamespace(qpos=d.qpos.copy()))
                    if task.reference_events[-1]["start_pose"] != e["start_pose"]:
                        raise ValueError("carry reference replay differs")
                elif kind == "world_goal":
                    task.cartesian_goal(
                        f, d, e["goal_m"], np.array(e["rotation"]), e["duration"]
                    )
                    actual = task.reference_events[-1]
                    if actual != e:
                        raise ValueError("world goal actual-state origin differs")
                elif kind == "world_reference_knots":
                    task.synchronize_reference(f, d)
                    actual = task.reference_events[-1]
                    a = np.array([x[1] for x in actual["knots"]])
                    b = np.array([x[1] for x in e["knots"]])
                    error = float(np.max(np.abs(a - b)))
                    max_knots = max(max_knots, error)
                    knot_checks += len(a)
                    if error > 1e-12 or task.failure:
                        raise ValueError("causal future IK differs")
                elif kind == "arm_goal":
                    task.arm_goal(f, e["angles_rad"], e["duration"])
                elif kind != "grip_anchor":
                    raise ValueError("unknown reference event " + kind)
        enc = np.asarray(
            [
                ENCODER_ASSEMBLER.assemble(
                    native.build_dynamic_g1_encoder_blocks(
                        task.q,
                        task.v,
                        frame,
                        initial_robot_quaternion_wxyz=initial,
                        current_robot_quaternion_wxyz=quaternions[-1],
                    )
                )
            ],
            dtype=np.float32,
        )
        err = float(
            np.max(
                np.abs(enc[0] - np.array(row["encoder_input_values"], dtype=np.float32))
            )
        )
        max_encoder = max(max_encoder, err)
        token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
        state_tick = index + 10
        inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)
        dec = np.asarray(
            [
                DECODER_ASSEMBLER.assemble(
                    official_decoder_blocks(
                        inputs,
                        state_tick,
                        token,
                        last_action_rows(applied, state_tick, legacy=False),
                    )
                )
            ],
            dtype=np.float32,
        )
        raw = np.asarray(
            decoder.run(None, {decoder.get_inputs()[0].name: dec})[0]
        ).reshape(29)
        raw_error = float(
            np.max(np.abs(raw - np.array(row["raw_action_isaaclab"], dtype=np.float32)))
        )
        max_raw = max(max_raw, raw_error)
        if (
            hashlib.sha256(enc.tobytes()).hexdigest() != row["encoder_input_sha256"]
            or hashlib.sha256(dec.tobytes()).hexdigest() != row["decoder_input_sha256"]
            or raw_error != 0
        ):
            mismatches.append(
                {
                    "tick": index,
                    "frame": frame,
                    "encoder_error": err,
                    "raw_error": raw_error,
                }
            )
        reference_equal &= np.array_equal(
            task.q[frame], snapshots["per_tick_qpos"][index]
        )
        applied[state_tick] = reorder_mujoco_to_isaaclab(
            (np.array(row["hybrid_target_rad"]) - DEFAULT_ANGLES) / ACTION_SCALES
        )
    result = {
        "schema": "hybrid-causal-policy-audit/v1",
        "passed": not mismatches and bool(reference_equal),
        "checked_encoder_decoder_inputs": len(trace["records"]),
        "causally_resolved_future_IK_knots": knot_checks,
        "max_encoder_float32_error": max_encoder,
        "max_raw_action_float32_error": max_raw,
        "max_future_IK_error_rad": max_knots,
        "reference_snapshot_equal": bool(reference_equal),
        "mismatches": mismatches,
        "physics_steps": 0,
        "report": _file_binding(root / "REPORT.json"),
        "implementation": _file_binding(Path(__file__)),
        "scope": "recomputed future IK from current actual state, original ONNX encoder/decoder, mixed executed history; not task success by itself",
    }
    save(output, result)
    print(
        {
            k: v
            for k, v in result.items()
            if k not in ("mismatches", "report", "implementation")
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    audit(p.parse_args().root)
