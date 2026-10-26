"""Real-state SONIC chain with the frozen official ElasticBand support.

Every output lives in a new directory. Support is an explicit external wrench,
never evidence of free standing. The default shadow has zero candidate writes.
An independent active entrypoint must supply a verified shadow admission before
this shared engine can apply any SONIC target, following a fresh 50-tick shadow.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from . import sonic_native_dynamic_shadow as native
from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_native_full_shadow import _make_session
from .sonic_native_planner_preflight import _file_binding
from .sonic_offline_observation_mapper import build_decoder_blocks, prepare_decoder_state
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    ACTION_SCALES,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import SONIC_BODY_JOINT_ORDER
from .sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab

BRIDGE = native.DEFAULT_SOURCE / "gear_sonic/utils/mujoco_sim/unitree_sdk2py_bridge.py"
BASE_SIM = native.DEFAULT_SOURCE / "gear_sonic/utils/mujoco_sim/base_sim.py"
RUN_ROOT = native.DEFAULT_RUN_ROOT / "supported_observer_20261019"


def load_official_band() -> Any:
    """Execute only the actual frozen ElasticBand class, without SDK imports."""
    import numpy as np
    import scipy.spatial.transform

    tree = ast.parse(BRIDGE.read_text())
    band_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ElasticBand"
    )
    scope = {"np": np, "scipy": scipy}
    exec(compile(ast.Module(body=[band_class], type_ignores=[]), str(BRIDGE), "exec"), scope)
    return scope["ElasticBand"]()


def apply_official_band(mujoco: Any, model: Any, data: Any, band: Any, body: int) -> Any:
    """Mirror base_sim.sim_step: global body velocity, swap angular/linear."""
    import numpy as np

    pose = np.concatenate([data.xpos[body], data.xquat[body], np.zeros(6)])
    mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, pose[7:13], 0)
    pose[7:10], pose[10:13] = pose[10:13], pose[7:10].copy()
    expected = band.Advance(pose) if band.enable else np.zeros(6)
    # Do not zero unrelated writes: the external-wrench guard must detect them.
    data.xfrc_applied[body] = expected
    return expected.copy()


def last_action_rows(raw_actions: Any, tick: int, *, legacy: bool = False) -> Any:
    """Official LogFullState logs previous action before CreatePolicyCommand."""
    import numpy as np

    rows = np.zeros((tick + 1, 29), dtype=np.float32)
    if legacy:
        rows[:] = raw_actions[: tick + 1]
    elif tick:
        rows[1:] = raw_actions[:tick]
    return rows


def official_decoder_blocks(inputs: Any, tick: int, token: Any, actions: Any) -> dict[str, Any]:
    """Match GatherHisGravityDir even for StateLogger's zero quaternion padding.

    The C++ quat_rotate_d formula maps a zero quaternion and [0,0,-1] to
    [0,0,+1]. Padding gravity vectors with zero is therefore not equivalent.
    """
    blocks = build_decoder_blocks(
        inputs, tick, token_state=token, logged_last_actions_isaaclab=actions,
        prepared_state=prepare_decoder_state(inputs),
    )
    missing = max(0, 9 - tick)
    blocks["his_gravity_dir_10frame_step1"].reshape(10, 3)[:missing] = [0.0, 0.0, 1.0]
    return blocks


def build_reference(planner: Any, mode: int) -> tuple[Any, dict[str, Any], Any]:
    """Preserve official per-segment joint velocities through cross-fades."""
    import numpy as np

    def generate(context: Any, selected_mode: int) -> tuple[Any, dict[str, Any]]:
        raw, count, seconds = native._run_once(planner, native.build_planner_inputs(
            context, mode=selected_mode, random_seed=native.DEFAULT_RANDOM_SEED,
            movement_direction=(0.0, 0.0, 0.0) if selected_mode == 0 else (1.0, 0.0, 0.0),
            facing_direction=(1.0, 0.0, 0.0),
        ))
        valid, _, metrics = native.validate_planner_outputs(raw, count)
        return native.resample_qpos_50hz(valid), {**metrics, "inference_seconds": seconds}

    idle, init_metrics = generate(native.initialize_context(), 0)
    if mode == 0:
        # Official Initialize uses this first IDLE result directly. It does
        # not generate a second IDLE before the first policy observation.
        current, calls = idle, [init_metrics]
    else:
        current, first_metrics = generate(native.context_from_motion_50hz(idle), mode)
        calls = [init_metrics, first_metrics]
    velocity = native._reference_velocities(current)
    consumed, consumed_vel = [], []
    for _ in range(2):
        generated, metrics = generate(native.context_from_motion_50hz(current, generation_frame=52), mode)
        gen_vel = native._reference_velocities(generated)
        consumed.append(current[:50].copy())
        consumed_vel.append(velocity[:50].copy())
        count = 2 + generated.shape[0]
        old_indices = np.clip(np.arange(count) + 50, 0, len(current) - 1)
        new_indices = np.clip(np.arange(count) - 2, 0, len(generated) - 1)
        weight = np.clip((np.arange(count) - 2) / 8, 0, 1)[:, None]
        velocity = (1 - weight) * velocity[old_indices] + weight * gen_vel[new_indices]
        current = native.merge_planner_replan(current, generated, current_frame=50, generation_frame=52)
        calls.append(metrics)
    reference = np.concatenate([*consumed, current])
    return reference, {
        "mode": mode, "calls": calls, "frame_count_50hz": len(reference),
        "qpos_sha256": native._array_sha256(reference),
        "velocities_sha256": native._array_sha256(np.concatenate([*consumed_vel, velocity])),
        "horizontal_displacement_m": float(np.linalg.norm(reference[-1, :2] - reference[0, :2])),
        "velocity_seam": "blend_precomputed_segment_velocities_as_official_CurrentFrameAdvancement",
    }, np.concatenate([*consumed_vel, velocity])


def guard_candidate(candidate: Any, previous: Any, lower: Any, upper: Any) -> dict[str, Any]:
    import numpy as np

    candidate = np.asarray(candidate)
    delta = np.abs(candidate - previous)
    worst = int(np.argmax(delta))
    bad = np.flatnonzero((candidate < lower) | (candidate > upper))
    finite = bool(candidate.shape == (29,) and np.isfinite(candidate).all())
    return {
        "finite": finite,
        "in_range": bool(len(bad) == 0),
        "step_safe": bool(delta[worst] <= native.MAX_CANDIDATE_STEP_RAD),
        "max_step_rad": float(delta[worst]),
        "max_step_joint": SONIC_BODY_JOINT_ORDER[worst],
        "out_of_range_joints": [
            {"joint": SONIC_BODY_JOINT_ORDER[int(i)], "target_rad": float(candidate[i]),
             "lower_rad": float(lower[i]), "upper_rad": float(upper[i])}
            for i in bad
        ],
    }


def physical_guard(mujoco: Any, model: Any, data: Any, body: int, expected: Any) -> dict[str, Any]:
    import numpy as np

    external = data.xfrc_applied.copy()
    external[body] -= expected
    penetration, force = native._contact_metrics(mujoco, model, data)
    up = float(1 - 2 * (data.qpos[4] ** 2 + data.qpos[5] ** 2))
    return {
        "finite": bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all()
                       and np.isfinite(data.ctrl).all() and np.isfinite(data.xfrc_applied).all()),
        "only_declared_support_wrench": bool(not np.any(external) and not np.any(data.qfrc_applied)),
        "pelvis_height": bool(data.qpos[2] >= native.MIN_PELVIS_HEIGHT_M),
        "upright": bool(up >= native.MIN_PELVIS_UP_COMPONENT),
        "penetration": bool(penetration <= native.MAX_PENETRATION_M),
        "contact_force": bool(force <= native.MAX_CONTACT_FORCE_N),
        "pelvis_height_m": float(data.qpos[2]), "up_component": up,
        "penetration_m": penetration, "contact_force_n": force,
    }


PHYSICAL_GATE_NAMES = ("finite", "only_declared_support_wrench", "pelvis_height", "upright", "penetration", "contact_force")


def validated_admission(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text())
    content = {key: value for key, value in report.items() if key != "content_sha256_excluding_this_field"}
    if report.get("content_sha256_excluding_this_field") != canonical_sha256(content):
        raise RuntimeError("supported shadow admission hash mismatch")
    if (report.get("schema") != "sonic-supported-shadow/v1"
            or report.get("classification") != "passed"
            or report.get("sonic_only_physics_smoke_admission_ready") is not True
            or report.get("sonic_candidate_actuator_writes") != 0
            or report.get("source_a_body_reference_used") is not False
            or report.get("source_a_body_command_used") is not False
            or report.get("longest_safe_candidate_run_ticks", 0) < 50
            or report.get("history") != "previous_actual_applied_body_target_inverse_official_action_transform"
            or report.get("reference_playing") is not False
            or report.get("planner", {}).get("mode") != 0
            or report.get("warmup_measured_history_ticks") != 10
            or report.get("baseline_target_source") != "official_planner_reference_pd"
            or report.get("baseline_model_bias_compensation") is not True):
        raise RuntimeError("shadow does not admit this exact supported IDLE startup")
    if not all(report.get("physical_gates", {}).get(key) is True for key in PHYSICAL_GATE_NAMES):
        raise RuntimeError("shadow physical gates failed")
    thresholds = report.get("thresholds", {})
    expected = {"qualification_ticks": 50, "candidate_step_rad": native.MAX_CANDIDATE_STEP_RAD,
                "min_pelvis_m": native.MIN_PELVIS_HEIGHT_M, "min_up_component": native.MIN_PELVIS_UP_COMPONENT,
                "max_penetration_m": native.MAX_PENETRATION_M, "max_contact_force_n": native.MAX_CONTACT_FORCE_N}
    if thresholds != expected:
        raise RuntimeError("admission thresholds differ from the frozen gates")
    for binding in report["inputs"].values():
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise RuntimeError("admission input binding changed")
    for binding in report["source_bindings"].values():
        if sha256_file(Path(binding["path"])) != binding["sha256"]:
            raise RuntimeError("admission implementation/source binding changed")
    if sha256_file(Path(__file__)) != report["source_bindings"]["implementation"]["sha256"]:
        raise RuntimeError("active engine differs from the admitted shadow engine")
    trace_binding = report["trace"]
    if sha256_file(Path(trace_binding["path"])) != trace_binding["sha256"]:
        raise RuntimeError("admission trace file changed")
    trace = json.loads(Path(trace_binding["path"]).read_text())
    trace_content = {key: value for key, value in trace.items() if key != "content_sha256_excluding_this_field"}
    if trace.get("content_sha256_excluding_this_field") != canonical_sha256(trace_content):
        raise RuntimeError("admission trace content hash mismatch")
    records = trace["records"][:50]
    if len(records) != 50 or not all(row["candidate_safe"] for row in records):
        raise RuntimeError("initial 50-tick prefix is not safe")
    return {"report": report, "prefix": records, "binding": _file_binding(path)}


def run_shadow(output_root: Path, *, legacy_history: bool = False, reference_mode: int = 2,
               baseline_reference: bool = False, warmup_ticks: int = 0,
               paused_reference: bool = False, baseline_bias_compensation: bool = False,
               real_command_history: bool = False, active_admission: Path | None = None,
               band_lowering_steps: int = 0) -> dict[str, Any]:
    import mujoco
    import numpy as np
    import onnxruntime

    admission = validated_admission(active_admission) if active_admission else None
    if band_lowering_steps not in (0, 2):
        raise ValueError("only the declared default or two official lowering key presses are supported")
    if admission and admission["report"]["support"]["length_m"] != -0.1 * band_lowering_steps:
        raise RuntimeError("active support height must match the admission")
    if admission and not (real_command_history and reference_mode == 0 and baseline_reference
                          and warmup_ticks == 10 and paused_reference and baseline_bias_compensation
                          and not legacy_history):
        raise RuntimeError("active parameters must match the admitted startup")
    if output_root.exists():
        raise FileExistsError(f"refusing to overwrite an existing run: {output_root}")
    output_root.mkdir(parents=True)
    shutil.copyfile(__file__, output_root / "ENGINE_SNAPSHOT.py")
    started = time.monotonic()
    native._validated_prior_report(native.DEFAULT_FULL_SHADOW)
    bindings = {}
    for name, relative, digest in (
        ("planner", "planner/target_vel/V2/planner_sonic.onnx", native.EXPECTED_PLANNER_SHA256),
        ("encoder", "policy/sonic_v1_1/model_encoder.onnx", native.EXPECTED_ENCODER_SHA256),
        ("decoder", "policy/sonic_v1_1/model_decoder.onnx", native.EXPECTED_DECODER_SHA256),
        ("observations", "policy/sonic_v1_1/observation_config.yaml", native.EXPECTED_OBSERVATION_CONFIG_SHA256),
    ):
        path = native.DEFAULT_BUNDLE / relative
        if sha256_file(path) != digest:
            raise RuntimeError(f"official binding mismatch: {name}")
        bindings[name] = _file_binding(path)
    planner = _make_session(Path(bindings["planner"]["path"]))
    reference, planner_metrics, ref_vel = build_reference(planner, reference_mode)
    del planner
    if paused_reference:
        reference = np.repeat(reference[:1], 195, axis=0)
        ref_vel = np.zeros((195, 29))
    xml, stripped = native.stripped_official_model_xml(native.DEFAULT_MODEL)
    model = mujoco.MjModel.from_xml_string(xml.decode())
    model.opt.timestep = native.SIMULATION_DT_S
    ids = native._model_ids(mujoco, model)
    arrays = {key: np.asarray(value) for key, value in native.official_control_arrays().items()}
    model.dof_armature[ids["dof_ids"]] = arrays["armature"]
    lower, upper = model.jnt_range[ids["joint_ids"]].T.copy()
    defaults = np.asarray(DEFAULT_ANGLES)
    data = mujoco.MjData(model)
    data.qpos[ids["qpos_ids"]] = defaults
    mujoco.mj_forward(model, data)
    initial_quaternion = data.qpos[3:7].copy()
    band = load_official_band()
    for _ in range(band_lowering_steps):
        band.MujuocoKeyCallback(ord("7"))
    body = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    if body <= 0 or (model.nq, model.nv, model.nu) != (36, 35, 29):
        raise RuntimeError("official floating-base body contract mismatch")
    encoder = _make_session(Path(bindings["encoder"]["path"]))
    decoder = _make_session(Path(bindings["decoder"]["path"]))
    positions, velocities, quaternions, gyros = [], [], [], []
    control_ticks = 150 if admission else native.CONTROL_TICKS
    raw = np.zeros((control_ticks + warmup_ticks, 29), dtype=np.float32)
    applied_raw = np.zeros_like(raw)
    trace = []
    consecutive = longest = physical_steps = 0
    physical_pass = {key: True for key in PHYSICAL_GATE_NAMES}
    inference_seconds = []
    active_ticks = active_steps = 0
    stop_reason = None
    previous_applied_target = reference[0, 7:].copy() if baseline_reference else defaults.copy()
    warmup_trace = []
    for warmup in range(warmup_ticks):
        if stop_reason:
            break
        warmup_target = reference[0, 7:] if baseline_reference else defaults
        applied_raw[warmup] = reorder_mujoco_to_isaaclab((warmup_target - defaults) / np.asarray(ACTION_SCALES))
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quaternions.append(data.qpos[3:7].copy())
        local_velocity = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, local_velocity, 1)
        gyros.append(local_velocity[:3].copy())
        for _ in range(native.CONTROL_DECIMATION):
            support = apply_official_band(mujoco, model, data, band, body)
            baseline_target = reference[0, 7:] if baseline_reference else defaults
            torque = arrays["kp"] * (baseline_target - data.qpos[ids["qpos_ids"]]) - arrays["kd"] * data.qvel[ids["dof_ids"]]
            if baseline_bias_compensation:
                torque += data.qfrc_bias[ids["dof_ids"]]
            data.ctrl[ids["actuator_ids"]] = np.clip(torque, -arrays["effort_limit"], arrays["effort_limit"])
            mujoco.mj_step(model, data)
            physical_steps += 1
            metrics = physical_guard(mujoco, model, data, body, support)
            for key in physical_pass:
                physical_pass[key] &= metrics[key]
            warmup_trace.append({**metrics, "support_wrench": support.tolist()})
            if admission and not all(physical_pass.values()):
                stop_reason = "warmup_physical_guard_rejected"
                break
    for tick in range(control_ticks):
        tick_started = time.monotonic()
        is_active = admission is not None and tick >= native.QUALIFICATION_TICKS
        state_tick = tick + warmup_ticks
        positions.append(data.qpos[ids["qpos_ids"]].copy())
        velocities.append(data.qvel[ids["dof_ids"]].copy())
        quaternions.append(data.qpos[3:7].copy())
        local_velocity = np.zeros(6)
        mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, local_velocity, 1)
        gyros.append(local_velocity[:3].copy())
        inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)
        encoder_values = ENCODER_ASSEMBLER.assemble(native.build_dynamic_g1_encoder_blocks(
            reference, ref_vel, tick,
            initial_robot_quaternion_wxyz=initial_quaternion,
            current_robot_quaternion_wxyz=quaternions[-1],
        ))
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        start = time.perf_counter()
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_values = DECODER_ASSEMBLER.assemble(official_decoder_blocks(
            inputs, state_tick, token, last_action_rows(applied_raw if real_command_history else raw, state_tick, legacy=legacy_history)
        ))
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        raw[state_tick] = np.asarray(decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[0]).reshape(29)
        inference_seconds.append(time.perf_counter() - start)
        candidate = np.asarray(body_joint_target_from_raw_action(
            raw[state_tick], phase="official_walk_supported_shadow", sim_time_s=float(data.time)
        ).position_target_rad)
        previous = defaults if tick == 0 else np.asarray(trace[-1]["candidate_rad"])
        guard = guard_candidate(candidate, previous, lower, upper)
        safe = all(guard[key] for key in ("finite", "in_range", "step_safe"))
        consecutive = consecutive + 1 if safe else 0
        longest = max(longest, consecutive)
        substeps = []
        baseline_target = reference[tick, 7:] if baseline_reference else defaults
        prefix_match = admission is None or is_active or (
            candidate.tolist() == admission["prefix"][tick]["candidate_rad"]
            and hashlib.sha256(encoder_input.tobytes()).hexdigest() == admission["prefix"][tick]["encoder_input_sha256"]
            and hashlib.sha256(decoder_input.tobytes()).hexdigest() == admission["prefix"][tick]["decoder_input_sha256"]
        )
        handoff_step = float(np.max(np.abs(candidate - previous_applied_target))) if is_active and active_ticks == 0 else 0.0
        if admission and (not safe or not prefix_match or not all(physical_pass.values())
                          or (is_active and tick == 50 and consecutive < 50)
                          or handoff_step > native.MAX_CANDIDATE_STEP_RAD):
            stop_reason = "command_guard_or_prefix_or_handoff_rejected_before_write"
        target = candidate if is_active else baseline_target
        applied_raw[state_tick] = (raw[state_tick] if is_active else reorder_mujoco_to_isaaclab((target - defaults) / np.asarray(ACTION_SCALES)))
        for _ in range(native.CONTROL_DECIMATION):
            if stop_reason:
                break
            support = apply_official_band(mujoco, model, data, band, body)
            torque = arrays["kp"] * (target - data.qpos[ids["qpos_ids"]]) - arrays["kd"] * data.qvel[ids["dof_ids"]]
            if baseline_bias_compensation and not is_active:
                torque += data.qfrc_bias[ids["dof_ids"]]
            data.ctrl[ids["actuator_ids"]] = np.clip(torque, -arrays["effort_limit"], arrays["effort_limit"])
            mujoco.mj_step(model, data)
            physical_steps += 1
            if is_active:
                active_steps += 1
            metrics = physical_guard(mujoco, model, data, body, support)
            for key in physical_pass:
                physical_pass[key] &= metrics[key]
            substeps.append({**metrics, "support_wrench": support.tolist(),
                             "body_torque_nm": data.ctrl[ids["actuator_ids"]].tolist()})
            if admission and not all(physical_pass.values()):
                stop_reason = "physical_guard_rejected_after_step"
        if is_active and len(substeps) == 4:
            active_ticks += 1
        if substeps:
            previous_applied_target = target.copy()
        trace.append({
            "tick": tick, "candidate_guard": guard, "candidate_safe": safe,
            "consecutive_safe_ticks": consecutive, "candidate_rad": candidate.tolist(),
            "raw_action_isaaclab": raw[state_tick].tolist(),
            "actual_command_raw_equivalent_isaaclab": applied_raw[state_tick].tolist(),
            "reference_qpos": reference[tick].tolist(), "actual_qpos": inputs.body_position_mujoco_rad[-1].tolist(),
            "actual_qvel": inputs.body_velocity_mujoco_rad_s[-1].tolist(),
            "actual_quaternion": quaternions[-1].tolist(), "actual_gyro": gyros[-1].tolist(),
            "encoder_input_sha256": hashlib.sha256(encoder_input.tobytes()).hexdigest(),
            "decoder_input_sha256": hashlib.sha256(decoder_input.tobytes()).hexdigest(),
            "substeps": substeps, "sonic_candidate_consumed_by_physics": bool(is_active and substeps),
            "physics_command_source": "sonic_raw_target_official_pd" if is_active else "observer_baseline_pd",
            "handoff_step_from_last_real_target_rad": handoff_step,
            "admitted_shadow_prefix_matches": prefix_match,
        })
        if stop_reason:
            break
        if admission:
            time.sleep(max(0.0, native.CONTROL_DT_S - (time.monotonic() - tick_started)))
    trace_doc = {"schema": "sonic-supported-shadow-trace/v1", "records": trace, "warmup_substeps": warmup_trace}
    trace_doc["content_sha256_excluding_this_field"] = canonical_sha256(trace_doc)
    write_json_atomic(output_root / "TRACE.json", trace_doc)
    ready = all(physical_pass.values()) and longest >= native.QUALIFICATION_TICKS and not legacy_history
    active_pass = admission is not None and active_ticks == 100 and active_steps == 400 and stop_reason is None
    report = {
        "schema": "sonic-supported-active-smoke/v1" if admission else "sonic-supported-shadow/v1",
        "classification": "passed" if (active_pass if admission else ready) else "diagnostic",
        "inputs": bindings, "planner": planner_metrics,
        "source_bindings": {"elastic_band": _file_binding(BRIDGE), "base_sim": _file_binding(BASE_SIM),
                            "implementation": _file_binding(output_root / "ENGINE_SNAPSHOT.py"), "model": _file_binding(native.DEFAULT_MODEL),
                            **{name: _file_binding(Path(__file__).with_name(name + ".py")) for name in (
                                "sonic_native_dynamic_shadow", "sonic_native_full_shadow", "sonic_native_planner_preflight",
                                "sonic_offline_observation_mapper", "sonic_semantic_shadow", "sonic_native_active_smoke")}},
        "support": {"mode": "official_elastic_band_on_pelvis", "enabled": band.enable,
                    "kp_pos": band.kp_pos, "kd_pos": band.kd_pos, "kp_ang": band.kp_ang, "kd_ang": band.kd_ang,
                    "point_m": band.point.tolist(), "length_m": band.length,
                    "startup_lowering_key7_presses": band_lowering_steps,
                    "free_standing_validated": False, "external_wrench_recorded_every_substep": True},
        "model": {**stripped, "nq": model.nq, "nv": model.nv, "nu": model.nu, "ngeom": model.ngeom,
                  "collision_fidelity": "collision-lite; official inertias and primitive geoms only"},
        "history": ("previous_actual_applied_body_target_inverse_official_action_transform" if real_command_history
                    else "legacy_current_zero_diagnostic" if legacy_history else "previous_counterfactual_sonic_raw_at_current_state_tick"),
        "baseline_target_source": "official_planner_reference_pd" if baseline_reference else "official_fixed_default_pd",
        "baseline_model_bias_compensation": baseline_bias_compensation,
        "bias_compensation_scope": "observer baseline only; not an official SONIC policy or active controller feature",
        "gravity_padding": "official_zero_quaternion_rotates_gravity_to_positive_z",
        "primary_gyro": "pelvis_objectVelocity_local_angular; XML imu site is on torso and is not the primary gyro",
        "warmup_measured_history_ticks": warmup_ticks,
        "reference_playing": not paused_reference,
        "effective_reference": {"qpos_sha256": native._array_sha256(reference),
                                "velocities_sha256": native._array_sha256(ref_vel),
                                "pause_semantics": "official operator_state.play=false repeats current frame and zeros reference velocity" if paused_reference else None},
        "control_ticks": len(trace), "physics_steps": physical_steps,
        "physical_gates": physical_pass, "longest_safe_candidate_run_ticks": longest,
        "safe_candidate_ticks": sum(row["candidate_safe"] for row in trace),
        "maximum_candidate_step_rad": max(row["candidate_guard"]["max_step_rad"] for row in trace),
        "range_failure_ticks": [row["tick"] for row in trace if not row["candidate_guard"]["in_range"]],
        "thresholds": {"qualification_ticks": native.QUALIFICATION_TICKS, "candidate_step_rad": native.MAX_CANDIDATE_STEP_RAD,
                       "min_pelvis_m": native.MIN_PELVIS_HEIGHT_M, "min_up_component": native.MIN_PELVIS_UP_COMPONENT,
                       "max_penetration_m": native.MAX_PENETRATION_M, "max_contact_force_n": native.MAX_CONTACT_FORCE_N},
        "sonic_only_physics_smoke_admission_ready": ready and admission is None,
        "active_smoke_passed": active_pass,
        "active_control_ticks": active_ticks, "active_physics_steps": active_steps,
        "sonic_candidate_actuator_writes": active_steps,
        "active_body_controller": "raw SONIC target with official PD, effort saturation, no bias feedforward",
        "stop_reason": stop_reason, "admission": admission["binding"] if admission else None,
        "source_a_body_reference_used": False, "source_a_body_command_used": False,
        "full_mesh_collision_validated": False, "task_success_validated": False, "production_accepted": False,
        "trace": _file_binding(output_root / "TRACE.json"),
        "runtime": {"mujoco": mujoco.__version__, "numpy": np.__version__, "onnxruntime": onnxruntime.__version__,
                    "mean_policy_inference_seconds": float(np.mean(inference_seconds)), "wall_seconds": time.monotonic() - started},
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_root / "REPORT.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--legacy-history-diagnostic", action="store_true")
    parser.add_argument("--reference-mode", choices=(0, 2), type=int, default=2)
    parser.add_argument("--baseline-reference", action="store_true")
    parser.add_argument("--warmup-ticks", type=int, choices=(0, 10), default=0)
    parser.add_argument("--paused-reference", action="store_true")
    parser.add_argument("--baseline-bias-compensation", action="store_true")
    parser.add_argument("--real-command-history", action="store_true")
    parser.add_argument("--band-lowering-steps", choices=(0, 2), type=int, default=0)
    args = parser.parse_args()
    report = run_shadow(args.output_root, legacy_history=args.legacy_history_diagnostic,
                        reference_mode=args.reference_mode, baseline_reference=args.baseline_reference,
                        warmup_ticks=args.warmup_ticks, paused_reference=args.paused_reference,
                        baseline_bias_compensation=args.baseline_bias_compensation,
                        real_command_history=args.real_command_history,
                        band_lowering_steps=args.band_lowering_steps)
    print(json.dumps({key: report[key] for key in ("classification", "physical_gates", "longest_safe_candidate_run_ticks", "maximum_candidate_step_rad", "range_failure_ticks", "runtime")}, indent=2))
    return 0 if report["sonic_only_physics_smoke_admission_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
