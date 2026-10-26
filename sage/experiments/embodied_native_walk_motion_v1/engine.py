"""Real full-G1 steps with original SONIC29, official PD, neutral separate fingers.

Every write is bounded by the environment approval, frozen protocol and admission.
There is no band, free-root wrench, reset, body teleport, task prop or payload.
"""

import argparse
from pathlib import Path
import hashlib
import time
import shutil
import numpy as np
from .reference import Clock
from .metrics import measure
from sage.experiments.embodied_native_walk_v1.motion_gate import require_motion_protocol
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


def hand_ids(model):
    names = [
        model.joint(i).name
        for i in range(model.njnt)
        if "_hand_" in model.joint(i).name
    ]
    return {
        "names": names,
        "qpos": np.array([model.joint(n).qposadr[0] for n in names]),
        "dofs": np.array([model.joint(n).dofadr[0] for n in names]),
        "actuators": np.array([model.actuator(n).id for n in names]),
        "kp": np.array([2.0 if "thumb_0" in n else 1.5 for n in names]),
        "kd": 0.1,
    }


def run(root, case_id, output, budget=100, admission=None, previous=None):
    import mujoco

    protocol = require_motion_protocol(root)
    if budget not in protocol["active_budgets_ticks"]:
        raise ValueError("undeclared duration")
    if output.exists():
        raise FileExistsError(output)
    case_binding = protocol["case_bindings"][case_id]
    case = read_bound_json(Path(case_binding["path"]))
    if sha256_file(Path(case_binding["path"])) != case_binding["sha256"]:
        raise ValueError("case changed")
    verified = None
    preceding = None
    if admission:
        a = read_bound_json(admission)
        check = read_bound_json(admission.with_name("AUDIT.json"))
        if (
            not a["admission_ready"]
            or not check["control_passed"]
            or a["case"]["sha256"] != case_binding["sha256"]
            or a["engine"]["sha256"] != sha256_file(Path(__file__))
        ):
            raise ValueError("fresh exact full-body admission required")
        verified = read_bound_json(Path(a["trace"]["path"]))
    if admission and budget > 100:
        if previous is None:
            raise ValueError("previous shorter safe prefix required")
        a = read_bound_json(previous)
        check = read_bound_json(previous.with_name("AUDIT.json"))
        if (
            not a["active_safety_passed"]
            or not check["control_passed"]
            or a["case"]["sha256"] != case_binding["sha256"]
            or a["active_budget_ticks"] >= budget
        ):
            raise ValueError("previous prefix rejected")
        preceding = [
            r
            for r in read_bound_json(Path(a["trace"]["path"]))["records"]
            if r["active"]
        ]
    scene = read_bound_json(root / "model/SCENE.json")
    for b in [scene["model"], *scene["assets"], *scene["sources"].values()]:
        if sha256_file(Path(b["path"])) != b["sha256"]:
            raise ValueError("scene asset changed")
    model = load_model(scene["model"]["path"])
    # Raw XML default is .002; the predeclared original SONIC runtime contract is .005.
    model.opt.timestep = native.SIMULATION_DT_S
    assert (model.nq, model.nv, model.nu, model.nbody, model.neq, model.nmocap) == (
        50,
        49,
        43,
        50,
        0,
        0,
    )
    data = mujoco.MjData(model)
    data.qpos[:] = case["initial_qpos"]
    mujoco.mj_forward(model, data)
    initial_qpos = data.qpos.copy()
    initial_qvel = data.qvel.copy()
    initial_quat = data.qpos[3:7].copy()
    ids = native._model_ids(mujoco, model)
    hand = hand_ids(model)
    control = {k: np.array(v) for k, v in native.official_control_arrays().items()}
    defaults = np.array(DEFAULT_ANGLES)
    lower, upper = model.jnt_range[ids["joint_ids"]].T
    base = np.load(protocol["reference_base"]["path"], allow_pickle=False)
    clock = Clock(base["q"], base["v"], case, protocol["brake_ticks"])
    encoder = _make_session(Path(protocol["inputs"]["encoder"]["path"]))
    decoder = _make_session(Path(protocol["inputs"]["decoder"]["path"]))
    output.mkdir(parents=True)
    shutil.copyfile(__file__, output / "ENGINE_SNAPSHOT.py")
    started = time.monotonic()
    warmup = []
    records = []
    all_measures = []
    active_measures = []
    positions = []
    velocities = []
    quaternions = []
    gyros = []
    total_ticks = 50 + budget if admission else 100
    applied_raw = np.zeros((total_ticks + 10, 29), dtype=np.float32)
    enc_inputs = []
    dec_inputs = []
    ref_frames = []
    ref_velocities = []
    physical_steps = active_ticks = 0
    stop_reason = None
    error = None
    rejected_command = None
    previous_target = clock.q[0, 7:].copy()
    pelvis = model.body("pelvis").id

    def history():
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quaternions.append(data.qpos[3:7].copy())
        g = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, pelvis, g, 1)
        gyros.append(g[:3].copy())

    def physical(target, active, phase, tick):
        nonlocal physical_steps, stop_reason
        before = data.qpos.copy()
        velocity_before = data.qvel.copy()
        warm_before = data.qacc_warmstart.copy()
        t = float(data.time)
        bias = np.zeros(29) if active else data.qfrc_bias[ids["dof_ids"]].copy()
        torque = (
            control["kp"] * (target - before[ids["qpos_ids"]])
            - control["kd"] * velocity_before[ids["dof_ids"]]
            + bias
        )
        data.ctrl[ids["actuator_ids"]] = np.clip(
            torque, -control["effort_limit"], control["effort_limit"]
        )
        hraw = (
            -hand["kp"] * before[hand["qpos"]]
            - hand["kd"] * velocity_before[hand["dofs"]]
        )
        data.ctrl[hand["actuators"]] = np.clip(
            hraw,
            model.actuator_ctrlrange[hand["actuators"], 0],
            model.actuator_ctrlrange[hand["actuators"], 1],
        )
        if np.any(data.xfrc_applied) or np.any(data.qfrc_applied):
            raise ValueError("undeclared applied force before step")
        mujoco.mj_step(model, data)
        physical_steps += 1
        if physical_steps % 100 == 0:
            save(
                output / "PHYSICS_PROGRESS.json",
                {
                    "physics_steps": physical_steps,
                    "simulator_time_s": float(data.time),
                    "active_ticks": active_ticks,
                    "phase": phase,
                },
            )
        mujoco.mj_forward(model, data)
        s = measure(mujoco, model, data, ids, before, t, phase)
        s.update(
            full_qpos_before=before.tolist(),
            full_qpos_after=data.qpos.tolist(),
            full_qvel_before=velocity_before.tolist(),
            full_qvel_after=data.qvel.tolist(),
            qacc_warmstart_before=warm_before.tolist(),
            qacc_warmstart_after=data.qacc_warmstart.tolist(),
            all_ctrl=data.ctrl.tolist(),
            position_target_rad=target.tolist(),
            body_feedforward_nm=bias.tolist(),
            body_torque_nm=data.ctrl[ids["actuator_ids"]].tolist(),
            active=bool(active),
            tick=tick,
        )
        all_measures.append(s)
        if active:
            active_measures.append(s)
        if not s["safe"]:
            stop_reason = "physical_quality_collision_or_effort_guard_rejected"
        return s

    try:
        for tick in range(10):
            history()
            target = clock.q[0, 7:].copy()
            if not all(
                guard_candidate(
                    target, defaults if tick == 0 else previous_target, lower, upper
                )[k]
                for k in ("finite", "in_range", "step_safe")
            ):
                stop_reason = "warmup_target_rejected_before_write"
                break
            applied_raw[tick] = reorder_mujoco_to_isaaclab(
                (target - defaults) / np.asarray(ACTION_SCALES)
            )
            for _ in range(4):
                warmup.append(physical(target, False, "observer", -10 + tick))
                if stop_reason:
                    break
            previous_target = target.copy()
            if stop_reason:
                break
        for tick in range(total_ticks):
            if stop_reason:
                break
            active = bool(admission and tick >= 50)
            frame = 0
            if active:
                frame = clock.update(tick - 50, data, active_measures)
                if clock.failure:
                    stop_reason = clock.failure
                    break
                if clock.done:
                    break
            history()
            state_tick = tick + 10
            inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)
            enc = np.array(
                [
                    ENCODER_ASSEMBLER.assemble(
                        native.build_dynamic_g1_encoder_blocks(
                            clock.q,
                            clock.v,
                            frame,
                            initial_robot_quaternion_wxyz=initial_quat,
                            current_robot_quaternion_wxyz=quaternions[-1],
                        )
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
                            state_tick,
                            token,
                            last_action_rows(applied_raw, state_tick, legacy=False),
                        )
                    )
                ],
                dtype=np.float32,
            )
            raw = np.asarray(
                decoder.run(None, {decoder.get_inputs()[0].name: dec})[0],
                dtype=np.float32,
            ).reshape(29)
            candidate = np.asarray(
                body_joint_target_from_raw_action(
                    raw, phase="native_walk", sim_time_s=float(data.time)
                ).position_target_rad
            )
            guard = guard_candidate(
                candidate,
                defaults if tick == 0 else np.array(records[-1]["candidate_rad"]),
                lower,
                upper,
            )
            candidate_safe = all(guard[k] for k in ("finite", "in_range", "step_safe"))
            eh = hashlib.sha256(enc.tobytes()).hexdigest()
            dh = hashlib.sha256(dec.tobytes()).hexdigest()
            prefix = True
            if admission and not active:
                old = verified["records"][tick]
                prefix = (
                    old["encoder_input_sha256"] == eh
                    and old["decoder_input_sha256"] == dh
                    and old["candidate_rad"] == candidate.tolist()
                )
            target = candidate.copy() if active else clock.q[0, 7:].copy()
            executed_guard = guard_candidate(target, previous_target, lower, upper)
            if admission and (
                not candidate_safe
                or not prefix
                or not all(
                    executed_guard[k] for k in ("finite", "in_range", "step_safe")
                )
            ):
                rejected_command = {
                    "tick": tick,
                    "active": active,
                    "candidate_rad": candidate.tolist(),
                    "raw_action_isaaclab": raw.tolist(),
                    "candidate_guard": guard,
                    "executed_guard": executed_guard,
                    "prefix_match": prefix,
                    "clock": clock.snapshot(frame),
                    "encoder_input_values": enc[0].tolist(),
                    "decoder_input_values": dec[0].tolist(),
                }
                stop_reason = "candidate_prefix_or_handoff_rejected_before_write"
                break
            applied_raw[state_tick] = (
                raw
                if active
                else reorder_mujoco_to_isaaclab(
                    (target - defaults) / np.asarray(ACTION_SCALES)
                )
            )
            phase = clock.phase if active else "observer"
            row = {
                "tick": tick,
                "active": active,
                "reference_frame": frame,
                "phase": phase,
                "clock": clock.snapshot(frame),
                "candidate_rad": candidate.tolist(),
                "raw_action_isaaclab": raw.tolist(),
                "applied_raw_action_isaaclab": applied_raw[state_tick].tolist(),
                "target_rad": target.tolist(),
                "candidate_guard": guard,
                "candidate_safe": candidate_safe,
                "executed_guard": executed_guard,
                "prefix_match": prefix,
                "encoder_input_sha256": eh,
                "decoder_input_sha256": dh,
                "actual_qpos": positions[-1].tolist(),
                "actual_qvel": velocities[-1].tolist(),
                "actual_quaternion": quaternions[-1].tolist(),
                "actual_gyro": gyros[-1].tolist(),
                "substeps": [],
            }
            enc_inputs.append(enc[0].copy())
            dec_inputs.append(dec[0].copy())
            ref_frames.append(clock.q[frame].copy())
            ref_velocities.append(clock.v[frame].copy())
            for _ in range(4):
                row["substeps"].append(physical(target, active, phase, tick))
                if stop_reason:
                    break
            records.append(row)
            previous_target = target.copy()
            if active and len(row["substeps"]) == 4:
                active_ticks += 1
            if preceding and active and tick - 50 < len(preceding):
                if (
                    row["substeps"][-1]["full_qpos_after"]
                    != preceding[tick - 50]["substeps"][-1]["full_qpos_after"]
                ):
                    stop_reason = "earlier_safe_prefix_changed"
            if tick % 100 == 0:
                print(
                    {
                        "tick": tick,
                        "phase": phase,
                        "physics_steps": physical_steps,
                        "root": data.qpos[:3].tolist(),
                        "stop_reason": stop_reason,
                    },
                    flush=True,
                )
    except Exception as e:
        error = type(e).__name__ + ": " + str(e)
        stop_reason = "engineering_exception"
    trace = {
        "schema": "native-walk-physical-trace/v1",
        "initial_qpos": initial_qpos.tolist(),
        "initial_qvel": initial_qvel.tolist(),
        "warmup_substeps": warmup,
        "records": records,
        "reference_events": clock.events,
        "rejected_command": rejected_command,
    }
    save(output / "TRACE.json", trace)
    np.savez_compressed(
        output / "POLICY_IO.npz",
        encoder_inputs=np.asarray(enc_inputs, dtype=np.float32),
        decoder_inputs=np.asarray(dec_inputs, dtype=np.float32),
        per_tick_reference_qpos=np.asarray(ref_frames),
        per_tick_reference_velocity=np.asarray(ref_velocities),
    )
    task = evaluate(all_measures, case)
    ready = bool(
        not admission
        and not stop_reason
        and len(records) == 100
        and all(r["candidate_safe"] for r in records[:50])
    )
    active_safe = bool(
        admission and not stop_reason and (active_ticks == budget or clock.done)
    )
    task_passed = bool(active_safe and clock.done and task["task_metrics_passed"])
    report = {
        "schema": "native-walk-report/v1",
        "case": case_binding,
        "protocol": _file_binding(root / "MOTION_PROTOCOL.json"),
        "scene": _file_binding(root / "model/SCENE.json"),
        "model": scene["model"],
        "engine": _file_binding(Path(__file__)),
        "trace": _file_binding(output / "TRACE.json"),
        "policy_io": _file_binding(output / "POLICY_IO.npz"),
        "admission": None if admission is None else _file_binding(admission),
        "previous": None if previous is None else _file_binding(previous),
        "active_budget_ticks": budget,
        "admission_ready": ready,
        "active_safety_passed": active_safe,
        "task_passed": task_passed,
        "task_metrics": task,
        "physics_steps": max(
            physical_steps, int(round(data.time / native.SIMULATION_DT_S))
        ),
        "active_ticks": active_ticks,
        "stop_reason": stop_reason,
        "error": error,
        "final_phase": clock.phase,
        "reference_events": clock.events,
        "control_contract": "SONIC29 original raw all body outputs; neutral14finger PD; baseline motor gravity feedforward only; no applied force ever",
        "runtime": {
            "wall_s": time.monotonic() - started,
            "simulation_dt_s": native.SIMULATION_DT_S,
            "raw_model_timestep_s": 0.002,
        },
        "source_role": "development_validation",
        "dataset_split": "unassigned",
        "privileged_simulator_feedback": True,
        "no_external_support": True,
        "classification": (
            "task_passed"
            if task_passed
            else "admitted" if ready else "safe_prefix" if active_safe else "rejected"
        ),
    }
    save(output / "REPORT.json", report)
    print(
        {
            k: report[k]
            for k in (
                "classification",
                "physics_steps",
                "active_ticks",
                "final_phase",
                "stop_reason",
                "error",
            )
        },
        flush=True,
    )
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ticks", type=int, default=100)
    p.add_argument("--admission", type=Path)
    p.add_argument("--previous", type=Path)
    a = p.parse_args()
    run(a.root, a.case, a.output, a.ticks, a.admission, a.previous)
