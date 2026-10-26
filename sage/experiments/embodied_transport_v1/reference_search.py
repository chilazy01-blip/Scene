"""Bounded quantization-aware reference search; no integration or action writes."""

import argparse
import hashlib
import os
from pathlib import Path
import resource
from types import SimpleNamespace
import numpy as np
from .task import Task, smooth
from scipy.stats import qmc
from .kinematics import ARM_NAMES, solve
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ACTION_SCALES,
    body_joint_target_from_raw_action,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    official_decoder_blocks,
    last_action_rows,
    guard_candidate,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
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


def causal_task(planner, case, model, mujoco, trace, frame):
    task = Task(planner, case, model, mujoco)
    for e in trace["reference_events"]:
        f = e["frame"]
        if f > frame:
            break
        kind = e["kind"]
        if kind == "brake":
            task.brake(f)
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
            row = next(
                r
                for r in trace["records"]
                if r["sonic_candidate_consumed_by_physics"] and r["reference_tick"] == f
            )
            task.begin_carry(
                f,
                SimpleNamespace(qpos=np.array(row["substeps"][0]["full_qpos_before"])),
            )
        elif kind != "grip_anchor":
            raise ValueError(kind)
    return task


def perturb(q, arm, frame, delta):
    changed = q.copy()
    changed[frame:, arm + 7] += smooth(np.arange(len(q) - frame) / 30)[:, None] * delta
    return changed


def run(root):
    import mujoco

    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:4])
    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    output = root / "QUANTIZED_SEARCH.json"
    if output.exists():
        raise FileExistsError(output)
    report = read_bound_json(root / "attempt_01/active_1000/REPORT.json")
    bindings = [
        report["case"],
        report["trace"],
        report["model"],
        *report["inputs"].values(),
        *report["source_bindings"].values(),
    ]
    for binding in bindings:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("evidence changed")
    protocol_path = root / "REFERENCE_SEARCH_PROTOCOL.json"
    if protocol_path.exists():
        raise FileExistsError(protocol_path)
    evidence = read_bound_json(root / "POLICY_SENSITIVITY.json")
    protocol = {
        "schema": "quantization-aware-reference-search-protocol/v1",
        "states": [400, 480],
        "candidates_per_state": 64,
        "max_policy_inferences": 130,
        "reference_delta_limit_rad": 0.30,
        "ramp_ticks": 30,
        "minimum_proxy_rms_improvement_fraction": 0.30,
        "max_non_arm_command_change_rad": 0.05,
        "original_candidate_guard_unchanged": True,
        "physics_budget": 0,
        "reason": "frozen official encoder has Round quantization; replace failed local smooth inverse with finite reference search, not new grasp geometry",
        "parent": _file_binding(root / "QUANTIZATION_REVIEW.json"),
        "report": _file_binding(root / "attempt_01/active_1000/REPORT.json"),
        "dependencies": {
            "search": _file_binding(Path(__file__)),
            "causal_probe": _file_binding(Path(__file__).with_name("policy_probe.py")),
        },
        "no_followup_physics_on_diagnostic_alone": True,
    }
    protocol["content_sha256_excluding_this_field"] = canonical_sha256(protocol)
    write_json_atomic(protocol_path, protocol)
    candidates = (qmc.Sobol(7, scramble=False).random_base2(6) * 2 - 1) * 0.30
    candidates[0] = 0
    case = read_bound_json(Path(report["case"]["path"]))
    trace = read_bound_json(Path(report["trace"]["path"]))
    m = mujoco.MjModel.from_xml_path(case["model_path"])
    m.opt.timestep = native.SIMULATION_DT_S
    d = mujoco.MjData(m)
    ids = native._model_ids(mujoco, m)
    pelvis = m.body("pelvis").id
    planner = _make_session(Path(report["inputs"]["planner"]["path"]))
    encoder = _make_session(Path(report["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(report["inputs"]["decoder"]["path"]))
    initial = np.array(trace["warmup_substeps"][0]["full_qpos_before"][3:7])
    positions = []
    velocities = []
    quaternions = []
    gyros = []
    for s in trace["warmup_substeps"][::4]:
        d.qpos[:] = s["full_qpos_before"]
        d.qvel[:] = s["full_qvel_before"]
        mujoco.mj_forward(m, d)
        positions.append(d.qpos[ids["qpos_ids"]].copy())
        velocities.append(d.qvel[ids["dof_ids"]].copy())
        quaternions.append(d.qpos[3:7].copy())
        gyro = np.zeros(6)
        mujoco.mj_objectVelocity(m, d, mujoco.mjtObj.mjOBJ_BODY, pelvis, gyro, 1)
        gyros.append(gyro[:3].copy())
    all_rows = trace["records"]
    applied = np.zeros((len(all_rows) + 10, 29), dtype=np.float32)
    initial_task = Task(planner, case, m, mujoco)
    baseline_raw = reorder_mujoco_to_isaaclab(
        (initial_task.q[0, 7:] - np.array(DEFAULT_ANGLES)) / np.array(ACTION_SCALES)
    )
    applied[:10] = baseline_raw
    control = native.official_control_arrays()
    results = []
    policy_evaluations = 0
    for row_index, row in enumerate(all_rows):
        positions.append(np.array(row["actual_qpos"]))
        velocities.append(np.array(row["actual_qvel"]))
        quaternions.append(np.array(row["actual_quaternion"]))
        gyros.append(np.array(row["actual_gyro"]))
        tick = row["tick"] + 10
        frame = row["reference_tick"]
        applied[tick] = (
            row["raw_action_isaaclab"]
            if row["sonic_candidate_consumed_by_physics"]
            else baseline_raw
        )
        if not row["sonic_candidate_consumed_by_physics"] or frame not in (400, 480):
            continue
        task = causal_task(planner, case, m, mujoco, trace, frame)
        inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)

        def infer(q, v):
            nonlocal policy_evaluations
            policy_evaluations += 1
            ev = ENCODER_ASSEMBLER.assemble(
                native.build_dynamic_g1_encoder_blocks(
                    q,
                    v,
                    frame,
                    initial_robot_quaternion_wxyz=initial,
                    current_robot_quaternion_wxyz=quaternions[-1],
                )
            )
            enc = np.asarray([ev], dtype=np.float32)
            token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
            dv = DECODER_ASSEMBLER.assemble(
                official_decoder_blocks(
                    inputs, tick, token, last_action_rows(applied, tick, legacy=False)
                )
            )
            dec = np.asarray([dv], dtype=np.float32)
            raw = np.asarray(
                decoder.run(None, {decoder.get_inputs()[0].name: dec})[0]
            ).reshape(29)
            command = np.array(
                body_joint_target_from_raw_action(
                    raw, phase="offline_sensitivity", sim_time_s=0
                ).position_target_rad
            )
            return (
                command,
                hashlib.sha256(enc.tobytes()).hexdigest(),
                hashlib.sha256(dec.tobytes()).hexdigest(),
                raw,
            )

        base, eh, dh, raw = infer(task.q, task.v)
        exact = (
            eh == row["encoder_input_sha256"]
            and dh == row["decoder_input_sha256"]
            and np.array_equal(
                raw, np.array(row["raw_action_isaaclab"], dtype=np.float32)
            )
        )
        if not exact:
            raise ValueError(
                f'exact replay failed frame{frame}: encoder{eh==row["encoder_input_sha256"]} decoder{dh==row["decoder_input_sha256"]}'
            )
        frozen = next(p for p in evidence["probes"] if p["frame"] == frame)
        desired_command = np.array(frozen["desired_quasistatic_arm_command_rad"])
        baseline_error = float(
            np.sqrt(np.mean((desired_command - base[task.arm]) ** 2))
        )
        previous = np.array(all_rows[row_index - 1]["candidate_rad"])
        lower, upper = m.jnt_range[ids["joint_ids"]].T
        arm_bounds = np.array([m.joint(n).range for n in ARM_NAMES])
        other = np.array([i for i in range(29) if i not in task.arm])
        trials = []
        for number, delta in enumerate(candidates):
            q = perturb(task.q, task.arm, frame, delta)
            ref_ok = bool(
                np.all(q[frame:, task.arm + 7] >= arm_bounds[:, 0] + 1e-5)
                and np.all(q[frame:, task.arm + 7] <= arm_bounds[:, 1] - 1e-5)
            )
            if not ref_ok:
                trials.append(
                    {
                        "candidate": number,
                        "reference_delta_rad": delta.tolist(),
                        "eligible": False,
                        "reason": "reference_joint_range",
                    }
                )
                continue
            command, enc_hash, dec_hash, predicted_raw = infer(
                q, native._reference_velocities(q)
            )
            guard = guard_candidate(command, previous, lower, upper)
            cross = float(np.max(np.abs(command[other] - base[other])))
            error = float(np.sqrt(np.mean((desired_command - command[task.arm]) ** 2)))
            eligible = (
                all(guard[k] for k in ("finite", "in_range", "step_safe"))
                and cross <= protocol["max_non_arm_command_change_rad"]
            )
            trials.append(
                {
                    "candidate": number,
                    "reference_delta_rad": delta.tolist(),
                    "eligible": bool(eligible),
                    "arm_proxy_rms_rad": error,
                    "non_arm_command_max_change_rad": cross,
                    "candidate_guard": guard,
                    "encoder_sha256": enc_hash,
                    "decoder_sha256": dec_hash,
                    "raw_action": predicted_raw.tolist(),
                    "body_target_rad": command.tolist(),
                }
            )
        eligible = [c for c in trials if c["eligible"]]
        best = min(eligible, key=lambda c: c["arm_proxy_rms_rad"]) if eligible else None
        improvement = 1 - best["arm_proxy_rms_rad"] / baseline_error if best else 0.0
        results.append(
            {
                "frame": frame,
                "baseline_exact": bool(exact),
                "baseline_proxy_rms_rad": baseline_error,
                "best": best,
                "improvement_fraction": improvement,
                "passed": improvement
                >= protocol["minimum_proxy_rms_improvement_fraction"],
                "candidates": trials,
            }
        )
    result = {
        "schema": "quantization-aware-reference-search/v1",
        "protocol": _file_binding(protocol_path),
        "probes": results,
        "passed": all(p["passed"] for p in results),
        "policy_inferences": policy_evaluations,
        "max_policy_inferences": 130,
        "new_physics_steps": 0,
        "body_command_writes": 0,
        "controller_changed": False,
        "task_passed": False,
        "scope": "frozen-state reference candidate selection; does not prove physical tracking, grasp or whole-body rollout safety",
        "implementation": _file_binding(Path(__file__)),
    }
    assert policy_evaluations <= 130 and len(results) == 2
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {
            "passed": result["passed"],
            "policy_inferences": policy_evaluations,
            "states": [
                {
                    k: p[k]
                    for k in (
                        "frame",
                        "baseline_proxy_rms_rad",
                        "improvement_fraction",
                        "passed",
                    )
                }
                for p in results
            ],
            "physics_steps": 0,
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
