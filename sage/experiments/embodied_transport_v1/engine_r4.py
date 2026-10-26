"""Bounded continuous transport rollout; raw SONIC remains sole body controller."""

import argparse
import hashlib
from pathlib import Path
import shutil
import time
import numpy as np
from .task_r4 import Task
from .metrics import observe
from sage.experiments.embodied_carry_v1.control import apply as apply_hand
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED
from sage.experiments.embodied_carry_v2.engine import foot_metrics
from sage.experiments.embodied_locomotion_v1.support import AnchoredBand
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _make_session,
)
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    apply_official_band,
    physical_guard,
    guard_candidate,
    official_decoder_blocks,
    last_action_rows,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ACTION_SCALES,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
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


def authorize(root):
    p = read_bound_json(root / "PROTOCOL.json")
    for b in [p["case"], *p["dependencies"].values()]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("frozen protocol dependency changed: " + b["path"])
    return p


def setup_hand(mujoco, model, data, case):
    names = [
        model.joint(i).name
        for i in range(model.njnt)
        if "_hand_" in model.joint(i).name
    ]
    q = np.array([model.joint(n).qposadr[0] for n in names], dtype=int)
    d = np.array([model.joint(n).dofadr[0] for n in names], dtype=int)
    a = np.array([model.actuator(n).id for n in names], dtype=int)
    data.qpos[q] = 0
    adr = int(model.joint("payload_free").qposadr[0])
    data.qpos[adr : adr + 7] = [*case["source_object_xyz_m"], 1.0, 0.0, 0.0, 0.0]
    mujoco.mj_forward(model, data)
    return {
        "names": names,
        "qpos": q,
        "dofs": d,
        "actuators": a,
        "target": np.zeros(14),
        "closed": np.array([RIGHT_CLOSED.get(n, 0) for n in names]),
        "kp": np.array([2.0 if "thumb_0" in n else 1.5 for n in names]),
        "kd": 0.1,
        "effort": model.actuator_ctrlrange[a, 1].copy(),
    }


def run(root, output, budget=100, admission=None, previous=None):
    import mujoco

    protocol = authorize(root)
    case = read_bound_json(root / "CASE.json")
    if budget not in protocol["active_budgets_ticks"]:
        raise ValueError("undeclared duration")
    if output.exists():
        raise FileExistsError(output)
    prior = None
    previous_trace = None
    if admission:
        prior = read_bound_json(admission)
        independent = read_bound_json(admission.with_name("AUDIT.json"))
        if (
            not independent["control_passed"]
            or not prior["admission_ready"]
            or prior["case"]["sha256"] != sha256_file(root / "CASE.json")
            or prior["engine_source_sha256"] != sha256_file(Path(__file__))
        ):
            raise ValueError("exact independent body admission required")
        verify_trace = read_bound_json(Path(prior["trace"]["path"]))
    if admission and budget > 100:
        if previous is None:
            raise ValueError("longer episode requires preceding safe prefix")
        previous_report = read_bound_json(previous)
        previous_audit = read_bound_json(previous.with_name("AUDIT.json"))
        if (
            not previous_report["active_safety_passed"]
            or not previous_audit["control_passed"]
            or previous_report["case"]["sha256"] != sha256_file(root / "CASE.json")
            or previous_report["active_budget_ticks"] >= budget
        ):
            raise ValueError("preceding duration not accepted")
        previous_trace = read_bound_json(Path(previous_report["trace"]["path"]))
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output / "ENGINE_SNAPSHOT.py")
    started = time.monotonic()
    bindings = {}
    for name, relative, digest in (
        (
            "planner",
            "planner/target_vel/V2/planner_sonic.onnx",
            native.EXPECTED_PLANNER_SHA256,
        ),
        (
            "encoder",
            "policy/sonic_v1_1/model_encoder.onnx",
            native.EXPECTED_ENCODER_SHA256,
        ),
        (
            "decoder",
            "policy/sonic_v1_1/model_decoder.onnx",
            native.EXPECTED_DECODER_SHA256,
        ),
    ):
        path = native.DEFAULT_BUNDLE / relative
        if sha256_file(path) != digest:
            raise ValueError("official model hash mismatch")
        bindings[name] = _file_binding(path)
    scene = read_bound_json(Path(case["scene_manifest_path"]))
    for b in [scene["model"], *scene["assets"]]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("scene model or asset changed")
    model = mujoco.MjModel.from_xml_path(case["model_path"])
    model.opt.timestep = native.SIMULATION_DT_S
    data = mujoco.MjData(model)
    ids = native._model_ids(mujoco, model)
    arrays = {k: np.array(v) for k, v in native.official_control_arrays().items()}
    defaults = np.array(DEFAULT_ANGLES)
    data.qpos[ids["qpos_ids"]] = defaults
    data.qpos[:2] = case["start_xy_m"]
    hand = setup_hand(mujoco, model, data, case)
    band = AnchoredBand(case["start_xy_m"], 0.0)
    for _ in range(2):
        band.MujuocoKeyCallback(ord("7"))
    pelvis = model.body("pelvis").id
    planner = _make_session(Path(bindings["planner"]["path"]))
    task = Task(planner, case, model, mujoco)
    del planner
    encoder = _make_session(Path(bindings["encoder"]["path"]))
    decoder = _make_session(Path(bindings["decoder"]["path"]))
    initial_quaternion = data.qpos[3:7].copy()
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    positions = []
    velocities = []
    quaternions = []
    gyros = []
    control_ticks = 50 + budget if admission else 100
    raw = np.zeros((control_ticks + 10, 29), dtype=np.float32)
    applied_raw = np.zeros_like(raw)
    records = []
    warmup = []
    physical_steps = active_steps = active_ticks = 0
    stop_reason = None
    previous_target = task.q[0, 7:].copy()
    reference_frames = []
    initial_metrics = observe(mujoco, model, data)

    def history():
        mujoco.mj_forward(model, data)
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quaternions.append(data.qpos[3:7].copy())
        gyro = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, gyro, 1)
        gyros.append(gyro[:3].copy())

    def physical(target, active, frame):
        nonlocal physical_steps, active_steps, stop_reason
        wrench = apply_official_band(mujoco, model, data, band, pelvis)
        before = data.qpos.copy()
        velocity_before = data.qvel.copy()
        torque = (
            arrays["kp"] * (target - data.qpos[ids["qpos_ids"]])
            - arrays["kd"] * data.qvel[ids["dof_ids"]]
        )
        if not active:
            torque += data.qfrc_bias[ids["dof_ids"]]
        data.ctrl[ids["actuator_ids"]] = np.clip(
            torque, -arrays["effort_limit"], arrays["effort_limit"]
        )
        hand["target"] = hand["closed"] * (task.hand_fraction(frame) if active else 0.0)
        hand_record = apply_hand(model, data, hand)
        mujoco.mj_step(model, data)
        mujoco.mj_forward(model, data)
        physical_steps += 1
        active_steps += int(active)
        safety = physical_guard(mujoco, model, data, pelvis, wrench)
        payload = observe(mujoco, model, data)
        sample = {
            **safety,
            "payload": payload,
            "full_qpos_before": before.tolist(),
            "full_qpos_after": data.qpos.tolist(),
            "full_qvel_before": velocity_before.tolist(),
            "full_qvel_after": data.qvel.tolist(),
            "all_ctrl": data.ctrl.tolist(),
            "qacc_warmstart_after": data.qacc_warmstart.tolist(),
            "xfrc_applied": data.xfrc_applied.tolist(),
            "qfrc_applied": data.qfrc_applied.tolist(),
            "hand_pd": hand_record,
            "position_target_rad": target.tolist(),
            "body_position_before_rad": before[ids["qpos_ids"]].tolist(),
            "body_velocity_before_rad_s": velocity_before[ids["dof_ids"]].tolist(),
            "body_torque_nm": data.ctrl[ids["actuator_ids"]].tolist(),
            "body_velocity_after_rad_s": data.qvel[ids["dof_ids"]].tolist(),
            "root_velocity_after_m_s": data.qvel[:3].tolist(),
            "support_enabled": bool(band.enable),
            "support_wrench": wrench.tolist(),
            "bias_feedforward_used": not active,
            "feet": foot_metrics(mujoco, model, data),
            "stage": task.stage,
            "simulator_time_s": float(data.time),
        }
        if not all(
            safety[k]
            for k in (
                "finite",
                "only_declared_support_wrench",
                "pelvis_height",
                "upright",
                "penetration",
                "contact_force",
            )
        ):
            stop_reason = "original_physical_guard_rejected"
        if (
            payload["scene_violation"]
            or payload["body_fixture_violation"]
            or payload["non_task_contact"]
            or payload["world_position_m"][2] < 0.25
        ):
            stop_reason = "task_scene_or_drop_guard_rejected"
        if (
            active
            and task.anchor is not None
            and task.stage in ("lift", "carry", "target_stop", "place")
            and np.linalg.norm(np.array(payload["local_position_m"]) - task.anchor)
            > 0.03
        ):
            stop_reason = "grip_slip_after_step"
        return sample

    for tick in range(10):
        history()
        target = task.q[0, 7:]
        applied_raw[tick] = reorder_mujoco_to_isaaclab(
            (target - defaults) / np.array(ACTION_SCALES)
        )
        for _ in range(4):
            warmup.append(physical(target, False, 0))
            if stop_reason:
                break
        if stop_reason:
            break
    last_metrics = warmup[-1]["payload"] if warmup else initial_metrics
    for tick in range(control_ticks):
        if stop_reason:
            break
        is_active = bool(admission and tick >= 50)
        frame = tick - 50 if is_active else 0
        if is_active:
            task.update(frame, data, last_metrics)
            if task.failure:
                stop_reason = task.failure
                break
        history()
        state_tick = tick + 10
        inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)
        values = ENCODER_ASSEMBLER.assemble(
            native.build_dynamic_g1_encoder_blocks(
                task.q,
                task.v,
                frame,
                initial_robot_quaternion_wxyz=initial_quaternion,
                current_robot_quaternion_wxyz=quaternions[-1],
            )
        )
        enc = np.asarray([values], dtype=np.float32)
        token = encoder.run(None, {encoder.get_inputs()[0].name: enc})[0]
        dv = DECODER_ASSEMBLER.assemble(
            official_decoder_blocks(
                inputs,
                state_tick,
                token,
                last_action_rows(applied_raw, state_tick, legacy=False),
            )
        )
        dec = np.asarray([dv], dtype=np.float32)
        raw[state_tick] = np.asarray(
            decoder.run(None, {decoder.get_inputs()[0].name: dec})[0]
        ).reshape(29)
        candidate = np.array(
            body_joint_target_from_raw_action(
                raw[state_tick],
                phase="continuous_transport",
                sim_time_s=float(data.time),
            ).position_target_rad
        )
        guard = guard_candidate(
            candidate,
            defaults if tick == 0 else records[-1]["candidate_rad"],
            lower,
            upper,
        )
        safe = all(guard[k] for k in ("finite", "in_range", "step_safe"))
        enc_hash = hashlib.sha256(enc.tobytes()).hexdigest()
        dec_hash = hashlib.sha256(dec.tobytes()).hexdigest()
        prefix = True
        if admission and not is_active:
            old = verify_trace["records"][tick]
            prefix = (
                old["encoder_input_sha256"] == enc_hash
                and old["decoder_input_sha256"] == dec_hash
                and old["candidate_rad"] == candidate.tolist()
            )
        if admission and (
            not safe
            or not prefix
            or (
                is_active
                and frame == 0
                and np.max(np.abs(candidate - previous_target))
                > native.MAX_CANDIDATE_STEP_RAD
            )
        ):
            stop_reason = "candidate_or_prefix_or_handoff_rejected_before_write"
            break
        target = candidate if is_active else task.q[0, 7:]
        applied_raw[state_tick] = (
            raw[state_tick]
            if is_active
            else reorder_mujoco_to_isaaclab(
                (target - defaults) / np.array(ACTION_SCALES)
            )
        )
        if is_active and frame == 0:
            band.handle_keyboard_button("9")
        substeps = []
        before_root = data.qpos[:3].copy()
        for _ in range(4):
            substeps.append(physical(target, is_active, frame))
            if stop_reason:
                break
        row = {
            "tick": tick,
            "reference_tick": frame,
            "sonic_candidate_consumed_by_physics": is_active,
            "candidate_rad": candidate.tolist(),
            "raw_action_isaaclab": raw[state_tick].tolist(),
            "candidate_safe": safe,
            "candidate_guard": guard,
            "encoder_input_sha256": enc_hash,
            "decoder_input_sha256": dec_hash,
            "encoder_input_values": enc[0].tolist(),
            "actual_qpos": positions[-1].tolist(),
            "actual_qvel": velocities[-1].tolist(),
            "actual_quaternion": quaternions[-1].tolist(),
            "actual_gyro": gyros[-1].tolist(),
            "actual_root_xyz_before_m": before_root.tolist(),
            "actual_root_xyz_after_m": data.qpos[:3].tolist(),
            "substeps": substeps,
            "task": task.snapshot(frame),
        }
        records.append(row)
        reference_frames.append(task.q[frame].copy())
        last_metrics = substeps[-1]["payload"]
        previous_target = target.copy()
        if is_active and len(substeps) == 4:
            active_ticks += 1
        if previous_trace and is_active:
            prior_active = [
                r
                for r in previous_trace["records"]
                if r["sonic_candidate_consumed_by_physics"]
            ]
            if (
                frame < len(prior_active)
                and row["substeps"][-1]["full_qpos_after"]
                != prior_active[frame]["substeps"][-1]["full_qpos_after"]
            ):
                stop_reason = "preceding_execution_prefix_changed"
        if stop_reason or (is_active and task.done):
            break
    trace = {
        "schema": "continuous-transport-trace/v1",
        "warmup_substeps": warmup,
        "records": records,
        "initial_object": initial_metrics,
        "task_events": task.events,
        "reference_events": task.reference_events,
    }
    trace["content_sha256_excluding_this_field"] = canonical_sha256(trace)
    write_json_atomic(output / "TRACE.json", trace)
    np.savez_compressed(
        output / "reference_snapshots.npz",
        per_tick_qpos=np.asarray(reference_frames),
        final_qpos=task.q,
        final_velocity=task.v,
    )
    ready = (
        not admission
        and stop_reason is None
        and len(records) == 100
        and all(r["candidate_safe"] for r in records[:50])
        and last_metrics["source_supported"]
        and not initial_metrics["hand_contact"]
    )
    active_pass = bool(
        admission and stop_reason is None and (active_ticks == budget or task.done)
    )
    report = {
        "schema": "continuous-transport-report/v1",
        "classification": (
            "task_passed"
            if task.done and active_pass
            else "safe_prefix" if active_pass else "admitted" if ready else "rejected"
        ),
        "case": _file_binding(root / "CASE.json"),
        "protocol": _file_binding(root / "PROTOCOL.json"),
        "engine_source_sha256": sha256_file(Path(__file__)),
        "source_bindings": protocol["dependencies"],
        "inputs": bindings,
        "scene": _file_binding(Path(case["scene_manifest_path"])),
        "model": scene["model"],
        "admission": _file_binding(admission) if admission else None,
        "previous": _file_binding(previous) if previous else None,
        "active_budget_ticks": budget,
        "admission_ready": bool(ready),
        "active_safety_passed": active_pass,
        "task_passed": bool(task.done and active_pass),
        "active_control_ticks": active_ticks,
        "active_physics_steps": active_steps,
        "physics_steps": physical_steps,
        "stop_reason": stop_reason,
        "final_stage": task.stage,
        "task_events": task.events,
        "max_retention_slip_m": task.max_slip,
        "trace": _file_binding(output / "TRACE.json"),
        "reference_snapshots": _file_binding(output / "reference_snapshots.npz"),
        "runtime": {
            "wall_seconds": time.monotonic() - started,
            "simulation_dt_s": native.SIMULATION_DT_S,
        },
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "privileged_simulator_feedback": True,
        "preloaded_object": False,
        "production_accepted": False,
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output / "REPORT.json", report)
    print(
        {
            k: report[k]
            for k in (
                "classification",
                "admission_ready",
                "active_safety_passed",
                "task_passed",
                "active_control_ticks",
                "final_stage",
                "stop_reason",
            )
        },
        flush=True,
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ticks", type=int, default=100)
    p.add_argument("--admission", type=Path)
    p.add_argument("--previous", type=Path)
    a = p.parse_args()
    run(a.root, a.output, a.ticks, a.admission, a.previous)
