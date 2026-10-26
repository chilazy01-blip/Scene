"""Reconstruct recorded physical state/contact/PD/NN history, zero integration."""

import argparse
from pathlib import Path
import hashlib
import numpy as np
from .reference import Clock
from .engine import hand_ids
from .metrics import measure
from .protocol import require_motion_protocol
from sage.experiments.embodied_native_walk_v1.acceptance_v1 import evaluate
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.prepare import save
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file
from sage.experiments.embodied_data_stability_v1.sonic_native_planner_preflight import (
    _file_binding,
)
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    guard_candidate,
    official_decoder_blocks,
    last_action_rows,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ACTION_SCALES,
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from sage.experiments.embodied_data_stability_v1.sonic_offline_observation_mapper import (
    reorder_mujoco_to_isaaclab,
)


def audit(root, episode):
    import mujoco

    p = require_motion_protocol(root)
    if (episode / "AUDIT.json").exists():
        raise FileExistsError("audit already exists")
    report = read_bound_json(episode / "REPORT.json")
    case = read_bound_json(Path(report["case"]["path"]))
    for binding in [
        report["trace"],
        report["policy_io"],
        report["case"],
        report["model"],
        report["engine"],
        report["protocol"],
    ]:
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise ValueError("episode source binding changed")
    trace = read_bound_json(Path(report["trace"]["path"]))
    io = np.load(report["policy_io"]["path"], allow_pickle=False)
    model = load_model(report["model"]["path"])
    model.opt.timestep = native.SIMULATION_DT_S
    data = mujoco.MjData(model)
    data.qpos[:] = trace["initial_qpos"]
    data.qvel[:] = trace["initial_qvel"]
    mujoco.mj_forward(model, data)
    assert trace["initial_qpos"] == case["initial_qpos"]
    ids = native._model_ids(mujoco, model)
    hand = hand_ids(model)
    controls = {k: np.array(v) for k, v in native.official_control_arrays().items()}
    defaults = np.array(DEFAULT_ANGLES)
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    base = np.load(p["reference_base"]["path"], allow_pickle=False)
    clock = Clock(base["q"], base["v"], case, p["brake_ticks"])
    enc_session = _make_session(Path(p["inputs"]["encoder"]["path"]))
    dec_session = _make_session(Path(p["inputs"]["decoder"]["path"]))
    gates = {
        n: True
        for n in (
            "state_chain",
            "time_chain",
            "native_motor_pd",
            "target_ranges_slew",
            "raw_sonic29_unchanged",
            "actual_action_history",
            "contact_reconstruction",
            "all_physical_quality",
            "no_external_force",
            "causal_reference",
            "policy_bitwise_replay",
            "observation_matches_physics",
        )
    }
    max_pd = max_contact = max_geometry = 0.0
    count = 0
    active_samples = []
    measured = []
    positions = []
    velocities = []
    quats = []
    gyros = []
    last_q = np.asarray(trace["initial_qpos"])
    last_v = np.asarray(trace["initial_qvel"])
    last_warm = data.qacc_warmstart.copy()
    last_time = 0.0
    last_target = defaults.copy()
    actions = np.zeros((len(trace["records"]) + 10, 29), dtype=np.float32)
    pelvis = model.body("pelvis").id

    def history():
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quats.append(data.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        gyros.append(g[:3].copy())

    def verify(s, phase, active, target):
        nonlocal count, last_q, last_v, last_warm, last_time, last_target, max_pd, max_contact, max_geometry
        gates["state_chain"] &= (
            np.array_equal(s["full_qpos_before"], last_q)
            and np.array_equal(s["full_qvel_before"], last_v)
            and np.array_equal(s["qacc_warmstart_before"], last_warm)
        )
        gates["time_chain"] &= (
            abs(s["time_before_s"] - last_time) < 1e-9
            and abs(s["time_after_s"] - s["time_before_s"] - 0.005) < 1e-9
        )
        guard = guard_candidate(
            np.asarray(s["position_target_rad"]), last_target, lower, upper
        )
        gates["target_ranges_slew"] &= all(
            guard[k] for k in ("finite", "in_range", "step_safe")
        )
        gates["raw_sonic29_unchanged"] &= s["position_target_rad"] == target.tolist()
        before = np.asarray(s["full_qpos_before"])
        vel = np.asarray(s["full_qvel_before"])
        data.qpos[:] = before
        data.qvel[:] = vel
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        mujoco.mj_comVel(model, data)
        bias = np.zeros(model.nv)
        mujoco.mj_rne(model, data, 0, bias)
        feed = np.zeros(29) if active else bias[ids["dof_ids"]]
        torque = np.clip(
            controls["kp"] * (target - before[ids["qpos_ids"]])
            - controls["kd"] * vel[ids["dof_ids"]]
            + feed,
            -controls["effort_limit"],
            controls["effort_limit"],
        )
        expected = np.zeros(model.nu)
        expected[ids["actuator_ids"]] = torque
        expected[hand["actuators"]] = np.clip(
            -hand["kp"] * before[hand["qpos"]] - hand["kd"] * vel[hand["dofs"]],
            model.actuator_ctrlrange[hand["actuators"], 0],
            model.actuator_ctrlrange[hand["actuators"], 1],
        )
        error = max(
            float(np.max(np.abs(expected - np.asarray(s["all_ctrl"])))),
            float(np.max(np.abs(feed - np.asarray(s["body_feedforward_nm"])))),
        )
        max_pd = max(max_pd, error)
        gates["native_motor_pd"] &= error < 1e-8
        gates["no_external_force"] &= not np.any(s["xfrc_applied"]) and not np.any(
            s["qfrc_applied"]
        )
        data.qpos[:] = s["full_qpos_after"]
        data.qvel[:] = s["full_qvel_after"]
        data.qacc_warmstart[:] = s["qacc_warmstart_after"]
        data.ctrl[:] = s["all_ctrl"]
        data.xfrc_applied[:] = s["xfrc_applied"]
        data.qfrc_applied[:] = s["qfrc_applied"]
        data.time = s["time_after_s"]
        mujoco.mj_forward(model, data)
        actual = measure(mujoco, model, data, ids, before, s["time_before_s"], phase)
        gates["all_physical_quality"] &= (
            actual["safe"]
            and s["safe"]
            and s["phase"] == phase
            and s["active"] == active
        )
        max_geometry = max(
            max_geometry,
            float(
                np.max(np.abs(np.asarray(actual["root_after_m"]) - s["root_after_m"]))
            ),
        )
        gates["contact_reconstruction"] &= len(actual["contacts"]) == len(s["contacts"])
        for a, b in zip(actual["contacts"], s["contacts"]):
            gates["contact_reconstruction"] &= (
                a["pair"] == b["pair"] and a["forbidden"] == b["forbidden"]
            )
            max_contact = max(
                max_contact,
                abs(a["normal_force_n"] - b["normal_force_n"]),
                abs(a["distance_m"] - b["distance_m"]),
            )
        for side in ("left", "right"):
            max_contact = max(
                max_contact,
                abs(
                    actual["feet"][side]["ground_force_n"]
                    - s["feet"][side]["ground_force_n"]
                ),
            )
            max_geometry = max(
                max_geometry,
                abs(
                    actual["feet"][side]["clearance_m"] - s["feet"][side]["clearance_m"]
                ),
            )
        measured.append(actual)
        if active:
            active_samples.append(actual)
        last_q = np.array(s["full_qpos_after"])
        last_v = np.array(s["full_qvel_after"])
        last_warm = np.array(s["qacc_warmstart_after"])
        last_time = s["time_after_s"]
        last_target = target.copy()
        count += 1

    for i in range(0, len(trace["warmup_substeps"]), 4):
        history()
        target = clock.q[0, 7:].copy()
        actions[i // 4] = reorder_mujoco_to_isaaclab(
            (target - defaults) / np.asarray(ACTION_SCALES)
        )
        for s in trace["warmup_substeps"][i : i + 4]:
            verify(s, "observer", False, target)
    for i, row in enumerate(trace["records"]):
        active = row["active"]
        frame = clock.update(row["tick"], data, active_samples) if active else 0
        phase = clock.phase if active else "observer"
        gates["causal_reference"] &= frame == row["reference_frame"] and row[
            "clock"
        ] == clock.snapshot(frame)
        gates["causal_reference"] &= np.array_equal(
            clock.q[frame], io["per_tick_reference_qpos"][i]
        ) and np.array_equal(clock.v[frame], io["per_tick_reference_velocity"][i])
        history()
        state_tick = row["tick"] + 10
        gates["observation_matches_physics"] &= (
            np.array_equal(positions[-1], row["actual_qpos"])
            and np.array_equal(velocities[-1], row["actual_qvel"])
            and np.array_equal(quats[-1], row["actual_quaternion"])
            and np.max(np.abs(gyros[-1] - row["actual_gyro"])) < 1e-12
        )
        inputs = native._mapping_inputs(positions, velocities, quats, gyros)
        enc = np.array(
            [
                ENCODER_ASSEMBLER.assemble(
                    native.build_dynamic_g1_encoder_blocks(
                        clock.q,
                        clock.v,
                        frame,
                        initial_robot_quaternion_wxyz=trace["initial_qpos"][3:7],
                        current_robot_quaternion_wxyz=quats[-1],
                    )
                )
            ],
            dtype=np.float32,
        )
        token = enc_session.run(None, {enc_session.get_inputs()[0].name: enc})[0]
        dec = np.array(
            [
                DECODER_ASSEMBLER.assemble(
                    official_decoder_blocks(
                        inputs,
                        state_tick,
                        token,
                        last_action_rows(actions, state_tick, legacy=False),
                    )
                )
            ],
            dtype=np.float32,
        )
        raw = np.asarray(
            dec_session.run(None, {dec_session.get_inputs()[0].name: dec})[0],
            dtype=np.float32,
        ).reshape(29)
        gates["policy_bitwise_replay"] &= (
            np.array_equal(enc[0], io["encoder_inputs"][i])
            and np.array_equal(dec[0], io["decoder_inputs"][i])
            and np.array_equal(
                raw, np.asarray(row["raw_action_isaaclab"], dtype=np.float32)
            )
        )
        gates["policy_bitwise_replay"] &= (
            hashlib.sha256(enc.tobytes()).hexdigest() == row["encoder_input_sha256"]
            and hashlib.sha256(dec.tobytes()).hexdigest() == row["decoder_input_sha256"]
        )
        candidate = np.asarray(
            body_joint_target_from_raw_action(
                raw, phase="native_walk", sim_time_s=float(data.time)
            ).position_target_rad
        )
        gates["raw_sonic29_unchanged"] &= candidate.tolist() == row["candidate_rad"]
        target = candidate if active else clock.q[0, 7:].copy()
        actions[state_tick] = (
            raw
            if active
            else reorder_mujoco_to_isaaclab(
                (target - defaults) / np.asarray(ACTION_SCALES)
            )
        )
        gates["actual_action_history"] &= np.array_equal(
            actions[state_tick],
            np.asarray(row["applied_raw_action_isaaclab"], dtype=np.float32),
        )
        for s in row["substeps"]:
            verify(s, phase, active, target)
        if i % 100 == 0:
            print({"audit_tick": i, "state_samples": count}, flush=True)
    gates["causal_reference"] &= trace["reference_events"] == clock.events
    task = evaluate(measured, case)
    gates["contact_reconstruction"] &= max_contact < 1e-5 and max_geometry < 1e-10
    gates["exact_recorded_step_count"] = count == report["physics_steps"]
    gates["bounded_complete_prefix"] = bool(
        report["admission_ready"]
        if report["admission"] is None
        else report["active_safety_passed"]
    )
    control = all(gates.values())
    result = {
        "schema": "native-walk-independent-audit/v1",
        "control_passed": bool(control),
        "task_passed": bool(
            control and task["task_metrics_passed"] and report["task_passed"]
        ),
        "gates": {k: bool(v) for k, v in gates.items()},
        "task_metrics": task,
        "physics_steps": 0,
        "actual_samples_reconstructed": count,
        "max_pd_error_nm": max_pd,
        "max_contact_error": max_contact,
        "max_geometry_error_m": max_geometry,
        "policy_replayed_ticks": len(trace["records"]),
        "report": _file_binding(episode / "REPORT.json"),
        "implementation": _file_binding(Path(__file__)),
        "scope": "state/action/contact/causal NN reconstruction, not continuous dynamic reintegration; independent dynamics replay still required for final qualified episodes",
    }
    save(episode / "AUDIT.json", result)
    print(
        {
            "control_passed": result["control_passed"],
            "task_passed": result["task_passed"],
            "failed": [k for k, v in gates.items() if not v],
            "pd_error": max_pd,
            "contact_error": max_contact,
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--episode", type=Path, required=True)
    a = p.parse_args()
    audit(a.root, a.episode)
