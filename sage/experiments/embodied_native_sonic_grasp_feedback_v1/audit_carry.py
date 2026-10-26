from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
"""Independent zero-step PD/contact/state/causal reference and NN reconstruction."""

import argparse
from pathlib import Path
import numpy as np
from .protocol_carry import authorize, project_target
from .task_carry import Task
from sage.experiments.embodied_native_object_transport_v1.metrics import measure
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_data_stability_v1.audit_sonic_supported_execution import (
    read_bound_json,
)
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
from sage.experiments.embodied_data_stability_v1.audit_candidates import sha256_file


def audit(root, episode):
    import mujoco

    assert not (episode / "AUDIT.json").exists()
    p = authorize(root)
    r = read_bound_json(episode / "REPORT.json")
    c = read_bound_json(Path(r["case"]["path"]))
    for b in [r["trace"], r["policy_io"], r["model"], r["engine"], r["case"]]:
        assert sha256_file(Path(b["path"])) == b["sha256"]
    trace = read_bound_json(Path(r["trace"]["path"]))
    prefix_ticks = trace["checkpoint_continuation"]["prefix_active_ticks"]
    io = np.load(r["policy_io"]["path"], allow_pickle=False)
    model = load_model(r["model"]["path"])
    model.opt.timestep = 0.005
    data = mujoco.MjData(model)
    data.qpos[:] = trace["initial_qpos"]
    data.qvel[:] = trace["initial_qvel"]
    mujoco.mj_forward(model, data)
    assert trace["initial_qpos"][:50] == c["initial_robot_qpos"]
    ids = native._model_ids(mujoco, model)
    hand = hand_ids(model)
    gains = {k: np.asarray(v) for k, v in native.official_control_arrays().items()}
    base = np.load(p["reference"]["path"], allow_pickle=False)
    task = Task(mujoco, model, c, base["q"], base["v"])
    encsession = _make_session(Path(p["inputs"]["encoder"]["path"]))
    decsession = _make_session(Path(p["inputs"]["decoder"]["path"]))
    defaults = np.asarray(DEFAULT_ANGLES)
    scales = np.asarray(ACTION_SCALES)
    lo, hi = model.jnt_range[ids["joint_ids"]].T
    positions = []
    velocities = []
    quats = []
    gyros = []
    actions = np.zeros((len(trace["records"]) + 11, 29), dtype=np.float32)
    pelvis = model.body("pelvis").id
    measured = []
    count = 0
    hand_scene_count = 0
    lastq = data.qpos.copy()
    lastv = data.qvel.copy()
    lastwarm = data.qacc_warmstart.copy()
    lasttime = 0.0
    gates = {
        k: True
        for k in (
            "state_chain",
            "time_chain",
            "original43motor_pd",
            "no_external_forces",
            "contact_reconstruction",
            "all_recorded_physics_safe",
            "causal_reference",
            "actual_state_policy_observation",
            "encoder_decoder_bitwise",
            "original_raw_action_transform",
            "actual_mixed_and_projected_targets",
            "actual_applied_action_history",
            "policy_input_archive",
            "bounded_complete_episode",
            "sonic_controls_all29_body_joints",
        )
    }
    maxpd = maxcontact = maxgeometry = 0.0

    def history():
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quats.append(data.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        gyros.append(g[:3].copy())

    def verify(s, target, active):
        nonlocal lastq, lastv, lastwarm, lasttime, count, maxpd, maxcontact, maxgeometry, hand_scene_count
        before = np.asarray(s["full_qpos_before"])
        velocity = np.asarray(s["full_qvel_before"])
        gates["state_chain"] &= (
            np.array_equal(before, lastq)
            and np.array_equal(velocity, lastv)
            and np.array_equal(s["qacc_warmstart_before"], lastwarm)
        )
        gates["time_chain"] &= (
            s["time_before_s"] == lasttime
            and abs(s["time_after_s"] - lasttime - 0.005) < 1e-10
        )
        data.qpos[:] = before
        data.qvel[:] = velocity
        mujoco.mj_kinematics(model, data)
        mujoco.mj_comPos(model, data)
        mujoco.mj_comVel(model, data)
        bias = np.zeros(model.nv)
        mujoco.mj_rne(model, data, 0, bias)
        ff = np.zeros(29)
        if not active:
            ff[:] = bias[ids["dof_ids"]]
        expected = np.zeros(model.nu)
        expected[ids["actuator_ids"]] = np.clip(
            gains["kp"] * (target - before[ids["qpos_ids"]])
            - gains["kd"] * velocity[ids["dof_ids"]]
            + ff,
            np.maximum(-gains["effort_limit"], model.actuator_ctrlrange[ids["actuator_ids"], 0]),
            np.minimum(gains["effort_limit"], model.actuator_ctrlrange[ids["actuator_ids"], 1]),
        )
        expected[hand["actuators"]] = np.clip(
            hand["kp"] * (np.asarray(s["hand_target_rad"]) - before[hand["qpos"]])
            - hand["kd"] * velocity[hand["dofs"]],
            model.actuator_ctrlrange[hand["actuators"], 0],
            model.actuator_ctrlrange[hand["actuators"], 1],
        )
        maxpd = max(
            maxpd,
            float(np.max(np.abs(expected - np.asarray(s["all_ctrl"])))),
            float(np.max(np.abs(ff - np.asarray(s["body_feedforward_nm"])))),
        )
        gates["original43motor_pd"] &= maxpd < 1e-8
        gates["no_external_forces"] &= not np.any(s["xfrc_applied"]) and not np.any(
            s["qfrc_applied"]
        )
        data.qpos[:] = s["full_qpos_after"]
        data.qvel[:] = s["full_qvel_after"]
        data.qacc_warmstart[:] = s["qacc_warmstart_after"]
        data.time = s["time_after_s"]
        data.ctrl[:] = s["all_ctrl"]
        mujoco.mj_forward(model, data)
        actual = measure(mujoco, model, data, ids, velocity, c)
        hand_scene_count = (
            hand_scene_count + 1 if actual["hand_scene_force_n"] > 0.5 else 0
        )
        actual["gates"]["no_sustained_hand_desk_support"] = bool(
            hand_scene_count <= 30 and actual["hand_scene_force_n"] <= 10.0
        )
        actual["safe"] = all(actual["gates"].values())
        gates["all_recorded_physics_safe"] &= (
            actual["safe"] and s["safe"] and actual["gates"] == s["gates"]
        )
        gates["contact_reconstruction"] &= len(actual["contacts"]) == len(s["contacts"])
        for a, b in zip(actual["contacts"], s["contacts"]):
            gates["contact_reconstruction"] &= (
                a["pair"] == b["pair"] and a["forbidden"] == b["forbidden"]
            )
            maxcontact = max(
                maxcontact,
                abs(a["normal_force_n"] - b["normal_force_n"]),
                abs(a["force_norm_n"] - b["force_norm_n"]),
                abs(a["distance_m"] - b["distance_m"]),
            )
        maxgeometry = max(
            maxgeometry,
            float(np.max(np.abs(np.asarray(actual["object_m"]) - s["object_m"]))),
            abs(actual["object_bottom_m"] - s["object_bottom_m"]),
        )
        measured.append(actual)
        lastq = data.qpos.copy()
        lastv = data.qvel.copy()
        lastwarm = np.asarray(s["qacc_warmstart_after"])
        lasttime = float(data.time)
        count += 1

    for index in range(0, len(trace["warmup_substeps"]), 4):
        history()
        target = task.q[0, 7:].copy()
        actions[index // 4] = reorder_mujoco_to_isaaclab((target - defaults) / scales)
        for s in trace["warmup_substeps"][index : index + 4]:
            verify(s, target, False)
    saturation_runs = np.zeros(29, dtype=int)
    previous = task.q[0, 7:].copy()
    for index, row in enumerate(trace["records"]):
        tick = row["tick"]
        task.update(tick, data, measured[-1])
        task.synchronize(tick, data)
        gates["causal_reference"] &= (
            task.stage == row["stage"]
            and np.array_equal(task.q[tick], row["reference_qpos"])
            and np.array_equal(task.v[tick], row["reference_velocity"])
        )
        gates["causal_reference"] &= row["closure"] == task.closure
        expected_hand = task.hand_targets(hand["names"])
        gates["causal_reference"] &= all(s["hand_target_rad"] == expected_hand for s in row["substeps"])
        history()
        state = tick + 10
        gates["actual_state_policy_observation"] &= (
            np.array_equal(positions[-1], row["actual_body_qpos"])
            and np.array_equal(velocities[-1], row["actual_body_qvel"])
            and np.array_equal(quats[-1], row["actual_quaternion"])
            and np.max(np.abs(gyros[-1] - row["actual_gyro"])) < 1e-12
        )
        inputs = native._mapping_inputs(positions, velocities, quats, gyros)
        enc = np.array(
            [
                ENCODER_ASSEMBLER.assemble(
                    task.reference_blocks(tick, data, trace["initial_qpos"][3:7])
                )
            ],
            dtype=np.float32,
        )
        token = encsession.run(None, {encsession.get_inputs()[0].name: enc})[0]
        dec = np.array(
            [
                DECODER_ASSEMBLER.assemble(
                    official_decoder_blocks(
                        inputs,
                        state,
                        token,
                        last_action_rows(actions, state, legacy=False),
                    )
                )
            ],
            dtype=np.float32,
        )
        raw = np.asarray(
            decsession.run(None, {decsession.get_inputs()[0].name: dec})[0],
            dtype=np.float32,
        ).reshape(29)
        gates["encoder_decoder_bitwise"] &= np.array_equal(
            raw, np.asarray(row["raw_sonic_isaaclab"], dtype=np.float32)
        )
        gates["policy_input_archive"] &= np.array_equal(
            enc[0], io["encoder_inputs"][index]
        ) and np.array_equal(dec[0], io["decoder_inputs"][index])
        sonic = np.asarray(
            body_joint_target_from_raw_action(
                raw, phase="native_mug_transport", sim_time_s=float(data.time)
            ).position_target_rad
        )
        gates["original_raw_action_transform"] &= (
            sonic.tolist() == row["raw_sonic_target_rad"]
        )
        mixed = sonic.copy()
        projected, guard = project_target(
            mixed, previous, lo, hi, native.MAX_CANDIDATE_STEP_RAD, allow_slew=(tick >= 790)
        )
        saturation_runs = np.where(mixed != projected, saturation_runs + 1, 0)
        guard["saturation_run_ticks"] = saturation_runs.tolist()
        guard["sustained_one_second_joints"] = np.flatnonzero(saturation_runs >= 50).tolist()
        gates["sonic_controls_all29_body_joints"] &= (mixed.tolist() == row["raw_sonic_target_rad"] and row["body_action_source"] == "SONIC29" and row["independent_arm_actuation"] is False)
        gates["actual_mixed_and_projected_targets"] &= (
            mixed.tolist() == row["mixed_target_rad"]
            and projected.tolist() == row["target_rad"]
            and guard == row["projection"]
        )
        action = reorder_mujoco_to_isaaclab((projected - defaults) / scales)
        actions[state] = action
        gates["actual_applied_action_history"] &= np.array_equal(
            np.asarray(row["applied_action_isaaclab"], dtype=np.float32), actions[state]
        )
        for s in row["substeps"]:
            verify(s, projected, True)
        previous = projected.copy()
        if index % 100 == 0:
            print(
                {
                    "audit_tick": index,
                    "state_samples": count,
                    "pd_error": maxpd,
                    "contact_error": maxcontact,
                },
                flush=True,
            )
    gates["contact_reconstruction"] &= maxcontact < 1e-5 and maxgeometry < 1e-10
    gates["bounded_complete_episode"] = bool(
        (r["admission_passed"] or r["task_passed"])
        and r["stop_reason"] is None
        and count == r["physics_steps"]
    )
    if r["task_passed"]:
        task.update(len(trace["records"]), data, measured[-1])
        gates["causal_reference"] &= task.done and task.events == trace["events"]
    parent_trace = read_bound_json(root / "carry_prefix/TRACE.json")
    gates["checkpoint_executed_prefix_exact"] = trace["warmup_substeps"] == parent_trace["warmup_substeps"] and trace["records"][:prefix_ticks] == parent_trace["records"]
    passed = all(gates.values())
    result = {
        "schema": "native-mug-independent-audit/v1",
        "control_passed": bool(passed),
        "executed_control_reconstruction_passed": bool(all(v for k,v in gates.items() if k != "bounded_complete_episode")),
        "task_passed": bool(passed and r["task_passed"] and all(r["gates"].values())),
        "gates": {k: bool(v) for k, v in gates.items()},
        "max_pd_error_nm": maxpd,
        "max_contact_error": maxcontact,
        "max_geometry_error_m": maxgeometry,
        "state_samples": count,
        "nn_ticks": len(trace["records"]),
        "new_physics_steps": 0,
        "report": _file_binding(episode / "REPORT.json"),
        "implementation": _file_binding(Path(__file__)),
        "not_continuous_dynamics_reintegration": True,
    }
    safe_save(episode / "AUDIT.json", result)
    print(
        {
            "control_passed": passed,
            "task_passed": result["task_passed"],
            "failed": [k for k, v in gates.items() if not v],
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--episode", type=Path, required=True)
    a = ap.parse_args()
    audit(a.root, a.episode)


