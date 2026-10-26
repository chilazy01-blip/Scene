"""Actual native full-G1/mug integration, no root/object state writes after init."""

import argparse
from pathlib import Path
import shutil
import time
import numpy as np
from .protocol_fast import authorize, reserve, project_target
from .task_fast import Task
from sage.experiments.embodied_native_sonic_transport_v1.control import feedforward
from sage.experiments.embodied_native_sonic_transport_v1.rate_adapter import project_target as body_target
from sage.experiments.embodied_native_sonic_transport_v1.restore import restore
from sage.experiments.embodied_native_sonic_transport_v1.effort_adapter import native_torque
from sage.experiments.embodied_native_object_transport_v1.metrics import measure
from sage.experiments.embodied_native_walk_motion_v2.engine import hand_ids
from sage.experiments.embodied_transport_native_v1.model import load_model
from sage.experiments.embodied_transport_hybrid_v1.control import ARM
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_native_object_transport_v1.report_safe_engine import safe_save as save
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


def run(root, output, ticks, admission=None):
    import mujoco
    import os
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (16 * 1024**3, 16 * 1024**3))
    os.sched_setaffinity(0, sorted(os.sched_getaffinity(0))[:8])

    p = authorize(root)
    if ticks != p["full_ticks"]:
        raise ValueError("undeclared rollout duration")
    if output.exists():
        raise FileExistsError(output)
    prefix_episode = root / "contact_torque_prefix"
    prefix_trace = read_bound_json(prefix_episode / "TRACE.json")
    prefix_report = read_bound_json(prefix_episode / "REPORT.json")
    prior = None
    reserve(root, output, 40 + 4 * ticks)
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output / "ENGINE_SNAPSHOT.py")
    c = read_bound_json(Path(p["case"]["path"]))
    scene = read_bound_json(Path(p["scene"]["path"]))
    for b in [scene["model"], *scene["assets"], *scene["sources"].values()]:
        from sage.experiments.embodied_data_stability_v1.audit_candidates import (
            sha256_file,
        )

        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("changed model asset")
    model = load_model(scene["model"]["path"])
    model.opt.timestep = 0.005
    data = mujoco.MjData(model)
    data.qpos[:50] = c["initial_robot_qpos"]
    payload = int(model.joint("payload_free").qposadr[0])
    data.qpos[payload : payload + 7] = [
        *c["source_object_xyz_m"],
        *c["source_object_quat"],
    ]
    mujoco.mj_forward(model, data)
    initialq = data.qpos.copy()
    initialv = data.qvel.copy()
    ids = native._model_ids(mujoco, model)
    hand = hand_ids(model)
    control = {k: np.asarray(v) for k, v in native.official_control_arrays().items()}
    base = np.load(p["reference"]["path"], allow_pickle=False)
    task = Task(mujoco, model, c, base["q"], base["v"])
    encoder = _make_session(Path(p["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(p["inputs"]["decoder"]["path"]))
    from .runtime import SonicRuntime, NativeDriver, validate_hand_transition
    from .contract import load_contract
    from .commands import CommandFrame
    contract = load_contract()
    runtime = SonicRuntime(contract, decoder, encoder)
    hand_bounds = np.array([[min(0., RIGHT_CLOSED.get(n, 0.)*.5), max(0., RIGHT_CLOSED.get(n, 0.)*.5)] for n in hand["names"]])
    driver = NativeDriver(mujoco, model, hand_bounds)
    held_hands = None
    defaults = np.asarray(DEFAULT_ANGLES)
    scales = np.asarray(ACTION_SCALES)
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    previous = task.q[0, 7:].copy()
    actions = np.zeros((ticks + 10, 29), dtype=np.float32)
    positions = []
    velocities = []
    quats = []
    gyros = []
    warmup = []
    records = []
    measurements = []
    enc_inputs = []
    dec_inputs = []
    refs = []
    refvs = []
    physical_steps = 0
    reason = None
    error = None
    rejected = None
    max_projection = 0.0
    projected_ticks = 0
    hand_scene_steps = 0
    saturation_runs = np.zeros(29, dtype=int)
    maximum_saturation_runs = np.zeros(29, dtype=int)
    pelvis = model.body("pelvis").id
    started = time.monotonic()

    def history():
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quats.append(data.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        gyros.append(g[:3].copy())

    def physical(target, closure, active, stage, tick):
        nonlocal physical_steps, reason, hand_scene_steps
        before = data.qpos.copy()
        velocity = data.qvel.copy()
        warm = data.qacc_warmstart.copy()
        t = float(data.time)
        bias = feedforward(data.qfrc_bias[ids["dof_ids"]], active)
        if held_hands is None:
            raise ValueError("no atomic hand command has been latched")
        htarget = held_hands
        data.ctrl[:], torque, htorque = driver.torques(data, target, htarget, active)
        if np.any(data.qfrc_applied) or np.any(data.xfrc_applied):
            raise ValueError("applied external force")
        mujoco.mj_step(model, data)
        physical_steps += 1
        mujoco.mj_forward(model, data)
        s = measure(mujoco, model, data, ids, velocity, c)
        hand_scene_steps = hand_scene_steps + 1 if s["hand_scene_force_n"] > 0.5 else 0
        s.update(
            time_before_s=t,
            time_after_s=float(data.time),
            stage=stage,
            active=bool(active),
            tick=tick,
            full_qpos_before=before.tolist(),
            full_qpos_after=data.qpos.tolist(),
            full_qvel_before=velocity.tolist(),
            full_qvel_after=data.qvel.tolist(),
            qacc_warmstart_before=warm.tolist(),
            qacc_warmstart_after=data.qacc_warmstart.tolist(),
            all_ctrl=data.ctrl.tolist(),
            body_requested_torque_nm=torque.tolist(),
            actual_body_actuator_force_nm=data.actuator_force[ids["actuator_ids"]].tolist(),
            finger_requested_torque_nm=htorque.tolist(),
            actual_finger_actuator_force_nm=data.actuator_force[hand["actuators"]].tolist(),
            body_position_target_rad=target.tolist(),
            body_feedforward_nm=bias.tolist(),
            hand_target_rad=htarget.tolist(),
            xfrc_applied=data.xfrc_applied.tolist(),
            qfrc_applied=data.qfrc_applied.tolist(),
        )
        s["gates"]["no_sustained_hand_desk_support"] = bool(
            hand_scene_steps <= 30 and s["hand_scene_force_n"] <= 10.0
        )
        s["safe"] = all(s["gates"].values())
        measurements.append(s)
        if not s["safe"]:
            reason = "physical_rejection:" + ",".join(
                k for k, v in s["gates"].items() if not v
            )
        if physical_steps % 100 == 0:
            save(
                output / "PROGRESS.json",
                {
                    "physics_steps": physical_steps,
                    "time_s": float(data.time),
                    "stage": stage,
                    "root": data.qpos[:3].tolist(),
                    "object": s["object_m"],
                    "stop_reason": reason,
                },
            )
            print(
                {
                    "step": physical_steps,
                    "time": round(float(data.time), 3),
                    "stage": stage,
                    "root": data.qpos[:3].round(4).tolist(),
                    "object": np.round(s["object_m"], 4).tolist(),
                    "stop": reason,
                },
                flush=True,
            )
        return s

    info = restore(mujoco, model, data, task, prefix_trace, actions, history, defaults, scales)
    prefix_steps = info["prefix_physics_steps"]
    prefix_ticks = info["prefix_active_ticks"]
    assert prefix_steps == 5244 and prefix_ticks == 1301
    warmup = prefix_trace["warmup_substeps"]
    records = list(prefix_trace["records"])
    measurements = list(warmup) + [s for row in records for s in row["substeps"]]
    physical_steps = prefix_steps
    previous = np.asarray(records[-1]["target_rad"])
    saturation_runs = np.asarray(records[-1]["projection"]["saturation_run_ticks"])
    maximum_saturation_runs = np.asarray(prefix_report["maximum_saturation_run_ticks"])
    max_projection = prefix_report["maximum_target_projection_rad"]
    projected_ticks = prefix_report["projected_ticks"]
    source_io = np.load(prefix_episode / "POLICY_IO.npz", allow_pickle=False)
    enc_inputs = [a.copy() for a in source_io["encoder_inputs"]]
    dec_inputs = [a.copy() for a in source_io["decoder_inputs"]]
    refs = [a.copy() for a in source_io["reference_qpos"]]
    refvs = [a.copy() for a in source_io["reference_velocity"]]
    hand_scene_steps = 0
    for sample in measurements:
        hand_scene_steps = hand_scene_steps + 1 if sample["hand_scene_force_n"] > .5 else 0
    slew_limited_ticks = 0
    checkpoint = dict(**info, parent_report=_file_binding(prefix_episode / "REPORT.json"),
                      parent_trace=_file_binding(prefix_episode / "TRACE.json"),
                      exact_state_restore_count=1, prefix_already_charged=True,
                      qualification_requires_original_case_continuous_replay=True)
    try:
        # The exact executed prefix was restored; it is not integrated again.
        for tick in range(0):
            history()
            target = task.q[0, 7:].copy()
            target, guard = project_target(
                target,
                defaults if tick == 0 else previous,
                lower,
                upper,
                native.MAX_CANDIDATE_STEP_RAD,
            )
            actions[tick] = reorder_mujoco_to_isaaclab((target - defaults) / scales)
            for _ in range(4):
                warmup.append(physical(target, 0.0, False, "warmup", tick - 10))
                if reason:
                    break
            previous = target.copy()
            if reason:
                break
        for tick in range(prefix_ticks, ticks):
            if reason:
                break
            if time.time() >= p["deadline_epoch_utc"]:
                reason = "stage_wall_deadline"
                break
            task.update(tick, data, measurements[-1])
            if task.failure:
                reason = task.failure
                break
            if task.done:
                break
            task.synchronize(tick, data)
            if task.failure:
                reason = task.failure
                break
            history()
            state = tick + 10
            inputs = native._mapping_inputs(positions, velocities, quats, gyros)
            enc = np.array(
                [
                    ENCODER_ASSEMBLER.assemble(
                        task.reference_blocks(tick, data, initialq[3:7])
                    )
                ],
                dtype=np.float32,
            )
            token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
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
            frame = CommandFrame.from_task(
                contract, token.reshape(64), hand["names"],
                task.hand_targets(hand["names"]), frame_index=tick,
                observation_time_s=float(data.time), source="native_mug_task_expert/fast_contact_v1",
            )
            decoded = runtime.decode(frame, dec[0], hand["names"], float(data.time))
            held_hands = decoded.hand_target
            prior_hand = np.asarray(records[-1]["substeps"][-1]["hand_target_rad"])
            validate_hand_transition(prior_hand,held_hands,task.stage)
            raw = decoded.raw_body
            sonic = decoded.body_target
            mixed = sonic.copy()
            try:
                target, guard = body_target(
                    mixed, previous, lower, upper, native.MAX_CANDIDATE_STEP_RAD, True
                )
            except ValueError as exc:
                rejected = {
                    "tick": tick,
                    "stage": task.stage,
                    "raw": raw.tolist(),
                    "mixed": mixed.tolist(),
                    "error": str(exc),
                }
                reason = str(exc)
                break
            saturated = np.asarray(mixed) != target
            saturation_runs = np.where(saturated, saturation_runs + 1, 0)
            maximum_saturation_runs = np.maximum(maximum_saturation_runs, saturation_runs)
            guard["saturation_run_ticks"] = saturation_runs.tolist()
            guard["sustained_one_second_joints"] = np.flatnonzero(saturation_runs >= 50).tolist()
            slew_limited_ticks += int(bool(guard["slew_limited_joints"]))
            max_projection = max(max_projection, guard["maximum_projection_rad"])
            projected_ticks += int(bool(guard["projected_joints"]))
            actual_raw = reorder_mujoco_to_isaaclab((target - defaults) / scales)
            actions[state] = actual_raw
            row = {
                "tick": tick,
                "stage": task.stage,
                "body_action_source": "SONIC29",
                "command_frame": frame.record(),
                "independent_arm_actuation": False,
                "wrist_position_m": data.xpos[task.wrist].tolist(),
                "wrist_reference_m": None if task.path is None else task.desired(tick)[0].tolist(),
                "raw_sonic_isaaclab": raw.tolist(),
                "raw_sonic_target_rad": sonic.tolist(),
                "mixed_target_rad": mixed.tolist(),
                "target_rad": target.tolist(),
                "applied_action_isaaclab": actual_raw.tolist(),
                "projection": guard,
                "closure": task.closure,
                "group_closures": None if task.group_values is None else task.group_values.copy(),
                "feedback_allocation": task.feedback_allocation,
                "wrench_quality": task.quality,
                "reference_qpos": task.q[tick].tolist(),
                "reference_velocity": task.v[tick].tolist(),
                "actual_body_qpos": positions[-1].tolist(),
                "actual_body_qvel": velocities[-1].tolist(),
                "actual_quaternion": quats[-1].tolist(),
                "actual_gyro": gyros[-1].tolist(),
                "substeps": [],
            }
            enc_inputs.append(enc[0].copy())
            dec_inputs.append(dec[0].copy())
            refs.append(task.q[tick].copy())
            refvs.append(task.v[tick].copy())
            for _ in range(4):
                row["substeps"].append(
                    physical(target, task.closure, True, task.stage, tick)
                )
                if reason:
                    break
            records.append(row)
            previous = target.copy()
            if prior is not None and tick < 100:
                old = prior["records"][tick]["substeps"][-1]
                if any(
                    old[k] != row["substeps"][-1][k]
                    for k in (
                        "full_qpos_after",
                        "full_qvel_after",
                        "qacc_warmstart_after",
                    )
                ):
                    reason = "admission_prefix_changed"
                    break
    except Exception as exc:
        error = type(exc).__name__ + ": " + str(exc)
        reason = "engineering_exception"
    if reason is None and not task.done:
        reason = "episode_budget_ceiling"
    trace = {
        "schema": "native-mug-full-state-trace/v1",
        "checkpoint_continuation": checkpoint,
        "initial_qpos": initialq.tolist(),
        "initial_qvel": initialv.tolist(),
        "warmup_substeps": warmup,
        "records": records,
        "events": task.events,
        "rejected_command": rejected,
    }
    save(output / "TRACE.json", trace)
    np.savez_compressed(
        output / "POLICY_IO.npz",
        encoder_inputs=np.asarray(enc_inputs, dtype=np.float32),
        decoder_inputs=np.asarray(dec_inputs, dtype=np.float32),
        reference_qpos=np.asarray(refs),
        reference_velocity=np.asarray(refvs),
    )
    final = measurements[-1]
    events = [e["stage"] for e in task.events if "stage" in e]
    phases = (
        "approach",
        "source_stop",
        "ready_arm",
        "preinsert",
        "lower",
        "insert",
        "close",
        "lift",
        "tuck",
        "carry",
        "target_stop",
        "place",
        "release",
        "retract",
        "settle",
        "done",
    )
    carry_distance = (
        0.0
        if task.carry_origin is None
        else float(np.linalg.norm(data.qpos[:2] - task.carry_origin))
    )
    object_distance = float(
        np.linalg.norm(
            np.asarray(final["object_m"])[:2] - np.asarray(c["source_object_xyz_m"])[:2]
        )
    )
    goal_error = float(
        np.linalg.norm(
            np.asarray(final["object_m"])[:2] - np.asarray(c["target_object_xyz_m"])[:2]
        )
    )
    tail = measurements[-200:]
    gates = {
        "all_physical_safe": all(s["safe"] for s in measurements),
        "complete_continuous_task": task.done and all(s in events for s in phases),
        "held_carry_distance": carry_distance >= 0.25,
        "object_transported": object_distance >= 0.25,
        "carry_both_foot_cycles": all(
            task.carry_cycles[s] >= 1 for s in ("left", "right")
        ),
        "goal_error": goal_error <= 0.10,
        "released_and_settled": len(tail) == 200
        and all(
            s["desk_supported"]
            and not s["hand_contact"]
            and np.linalg.norm(s["object_velocity_m_s"]) < 0.02
            and np.linalg.norm(s["root_velocity_m_s"]) < 0.06
            for s in tail
        ),
        "no_rejection": reason is None,
    }
    result = {
        "schema": "native-mug-task-report/v1",
        "task_passed": all(gates.values()),
        "grasp_test_passed": task.grasp_test_passed,
        "load_probe_passed": task.probe_passed,
        "admission_passed": ticks == 100
        and not reason
        and len(records) == 100
        and np.linalg.norm(
            np.asarray(final["object_m"])[:2] - np.asarray(c["source_object_xyz_m"])[:2]
        )
        < 0.01,
        "gates": {k: bool(v) for k, v in gates.items()},
        "physics_steps": physical_steps,
        "new_physics_steps": physical_steps - prefix_steps,
        "checkpoint_continuation": checkpoint,
        "slew_limited_ticks": slew_limited_ticks,
        "active_ticks": len(records),
        "stage": task.stage,
        "stop_reason": reason,
        "error": error,
        "events": task.events,
        "carry_distance_m": carry_distance,
        "object_displacement_xy_m": object_distance,
        "goal_error_m": goal_error,
        "carry_foot_cycles": task.carry_cycles,
        "max_held_slip_m": task.max_slip,
        "projected_ticks": projected_ticks,
        "maximum_saturation_run_ticks": maximum_saturation_runs.tolist(),
        "saturation_policy": "observe persistent saturation; stop for measured physical failure or original bounded stage stall, not saturation alone",
        "maximum_target_projection_rad": max_projection,
        "case": p["case"],
        "protocol": _file_binding(root / "FAST_CONTACT_PROTOCOL.json"),
        "scene": p["scene"],
        "model": scene["model"],
        "engine": _file_binding(Path(__file__)),
        "trace": _file_binding(output / "TRACE.json"),
        "policy_io": _file_binding(output / "POLICY_IO.npz"),
        "wall_s": time.monotonic() - started,
        "body_control": "SONIC29 original outputs with legal range projection; no arm override or active body gravity feedforward",
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "independent_audit_pending": True,
    }
    save(output / "REPORT.json", result)
    cost_output = output.parent / "cost"
    cost_output.mkdir(exist_ok=False)
    save(cost_output / "REPORT.json", dict(physics_steps=physical_steps-prefix_steps,
        episode_total_physics_steps=physical_steps, prefix_already_charged_steps=prefix_steps,
        episode_report=_file_binding(output / "REPORT.json"), accounting_only=True,
        implementation=_file_binding(Path(__file__))))
    print(
        {
            k: result[k]
            for k in (
                "task_passed",
                "admission_passed",
                "physics_steps",
                "stage",
                "stop_reason",
                "error",
            )
        },
        flush=True,
    )
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--admission", type=Path)
    a = ap.parse_args()
    run(a.root, a.output, a.ticks, a.admission)


