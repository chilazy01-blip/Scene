"""Finite, zero-integration reference-to-policy sensitivity on frozen real states."""

import argparse
import hashlib
import os
from pathlib import Path
import resource
from types import SimpleNamespace
import numpy as np
from .task import Task, smooth
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
    output = root / "POLICY_SENSITIVITY.json"
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
        jac = np.zeros((29, 7))
        epsilon = 0.025
        for j in range(7):
            delta = np.zeros(7)
            delta[j] = epsilon
            plus = perturb(task.q, task.arm, frame, delta)
            minus = perturb(task.q, task.arm, frame, -delta)
            a = infer(plus, native._reference_velocities(plus))[0]
            b = infer(minus, native._reference_velocities(minus))[0]
            jac[:, j] = (a - b) / (2 * epsilon)
        s = row["substeps"][0]
        d.qpos[:] = s["full_qpos_before"]
        d.qvel[:] = s["full_qvel_before"]
        mujoco.mj_forward(m, d)
        wrist = m.body("right_wrist_yaw_link").id
        goal = np.array(row["task"]["sub_goal_m"])
        desired_R = np.eye(3)
        ik = solve(mujoco, m, d.qpos, goal, desired_R)
        arm_qids = np.array([m.joint(n).qposadr[0] for n in ARM_NAMES])
        arm_dofs = np.array([m.joint(n).dofadr[0] for n in ARM_NAMES])
        ideal = d.qpos.copy()
        ideal[arm_qids] = ik["angles_rad"]
        d.qpos[:] = ideal
        d.qvel[:] = 0
        mujoco.mj_forward(m, d)
        desired_command = (
            np.array(ik["angles_rad"])
            + d.qfrc_bias[arm_dofs] / np.array(control["kp"])[task.arm]
        )
        error = desired_command - base[task.arm]
        J = jac[task.arm]
        delta = np.linalg.solve(J.T @ J + 0.02 * np.eye(7), J.T @ error)
        delta = np.clip(delta, -0.10, 0.10)
        candidate_q = perturb(task.q, task.arm, frame, delta)
        candidate = infer(candidate_q, native._reference_velocities(candidate_q))[0]
        prev = np.array(all_rows[row_index - 1]["candidate_rad"])
        lower, upper = m.jnt_range[ids["joint_ids"]].T
        guard = guard_candidate(candidate, prev, lower, upper)
        sv = np.linalg.svd(J, compute_uv=False)
        other = np.array([i for i in range(29) if i not in task.arm])
        results.append(
            {
                "frame": frame,
                "baseline_exact_encoder_decoder_and_raw": bool(exact),
                "reference_joint_names": list(ARM_NAMES),
                "finite_difference_epsilon_rad": epsilon,
                "body_command_jacobian_29x7": jac.tolist(),
                "arm_singular_values": sv.tolist(),
                "condition_number": float(sv[0] / max(sv[-1], 1e-12)),
                "reference_delta_rad": delta.tolist(),
                "baseline_arm_command_error_rms_rad": float(np.sqrt(np.mean(error**2))),
                "probe_arm_command_error_rms_rad": float(
                    np.sqrt(np.mean((desired_command - candidate[task.arm]) ** 2))
                ),
                "non_arm_command_max_change_rad": float(
                    np.max(np.abs(candidate[other] - base[other]))
                ),
                "candidate_guard": guard,
                "ideal_pose_ik": ik,
                "desired_quasistatic_arm_command_rad": desired_command.tolist(),
                "meaning": "instantaneous policy response at frozen actual state; gravity-compensated IK command is only a diagnostic target, not a verified physical trajectory",
            }
        )
    result = {
        "schema": "zero-physics-sonic-reference-sensitivity/v1",
        "report": _file_binding(root / "attempt_01/active_1000/REPORT.json"),
        "probes": results,
        "policy_inferences": policy_evaluations,
        "maximum_inferences": 32,
        "new_physics_steps": 0,
        "body_command_writes": 0,
        "controller_changed": False,
        "task_passed": False,
        "scope": "two fixed pre-contact states, 7x +/-25mrad reference probes and one bounded100mrad correction each; no grasp replay, no learned-policy training, no closed-loop success claim",
        "implementation": _file_binding(Path(__file__)),
    }
    assert policy_evaluations <= 32 and len(results) == 2
    result["content_sha256_excluding_this_field"] = canonical_sha256(result)
    write_json_atomic(output, result)
    print(
        {
            "probes": [
                {
                    k: p[k]
                    for k in (
                        "frame",
                        "baseline_exact_encoder_decoder_and_raw",
                        "condition_number",
                        "baseline_arm_command_error_rms_rad",
                        "probe_arm_command_error_rms_rad",
                        "non_arm_command_max_change_rad",
                        "candidate_guard",
                    )
                }
                for p in results
            ],
            "physics_steps": 0,
            "policy_inferences": policy_evaluations,
        }
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    run(p.parse_args().root)
