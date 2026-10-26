"""Bounded dynamic shadow for the complete official SONIC body chain.

The official kinematic planner supplies a walking reference and the official
SONIC v1.1 encoder/decoder observes real MuJoCo state.  Candidate SONIC joint
targets are recorded and guarded but never enter physics.  Physics is driven
only by a fixed standing target with the official 29-DoF motor parameters.

The released robot meshes in the pinned source tree are Git-LFS pointers, so
this admission stage removes mesh assets/geometries in memory.  It retains the
official inertias, joints, actuators, foot spheres, arm cylinders, and floor.
This is sufficient for a bounded state/command admission, not for full-body
collision validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_native_full_shadow import _make_session
from .sonic_native_planner_preflight import (
    DEFAULT_BUNDLE,
    DEFAULT_RANDOM_SEED,
    DEFAULT_RUN_ROOT,
    EXPECTED_DECODER_SHA256,
    EXPECTED_ENCODER_SHA256,
    EXPECTED_OBSERVATION_CONFIG_SHA256,
    EXPECTED_PLANNER_SHA256,
    _array_sha256,
    _file_binding,
    _quaternion_slerp,
    _run_once,
    build_planner_inputs,
    context_from_motion_50hz,
    initialize_context,
    resample_qpos_50hz,
    validate_planner_outputs,
)
from .sonic_offline_observation_mapper import (
    G1_FUTURE_FRAMES,
    G1_FUTURE_STEP,
    G1_LOOKAHEAD_TICKS,
    MappingInputs,
    _heading_quaternion,
    _quat_conjugate,
    _quat_multiply,
    _rotation_6d_rowwise,
    build_decoder_blocks,
    prepare_decoder_state,
    reorder_mujoco_to_isaaclab,
)
from .sonic_semantic_shadow import (
    ACTION_MOTOR_TYPES,
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    ENCODER_BLOCKS,
    MOTOR_PARAMETERS,
    NATURAL_FREQUENCY,
    body_joint_target_from_raw_action,
    parse_v11_config_order,
)
from .sonic_shadow import SONIC_BODY_JOINT_ORDER


SCHEMA = "sonic-native-dynamic-shadow/v1"
TRACE_SCHEMA = "sonic-native-dynamic-shadow-trace/v1"
CONTROL_DT_S = 0.02
SIMULATION_DT_S = 0.005
CONTROL_DECIMATION = 4
CONTROL_TICKS = 100
PHYSICS_STEPS = CONTROL_TICKS * CONTROL_DECIMATION
QUALIFICATION_TICKS = 50
REPLAN_AFTER_TICKS = 50
REPLAN_BLEND_TICKS = 8
MAX_CANDIDATE_STEP_RAD = 0.5433987842330933
MAX_PENETRATION_M = 0.010
MAX_CONTACT_FORCE_N = 600.0
MIN_PELVIS_HEIGHT_M = 0.65
MIN_PELVIS_UP_COMPONENT = 0.5

DEFAULT_OUTPUT = DEFAULT_RUN_ROOT / "SONIC_NATIVE_DYNAMIC_SHADOW.json"
DEFAULT_TRACE_OUTPUT = DEFAULT_RUN_ROOT / "SONIC_NATIVE_DYNAMIC_SHADOW_TRACE.json"
DEFAULT_FULL_SHADOW = DEFAULT_RUN_ROOT / "SONIC_NATIVE_FULL_ZERO_PHYSICS_SHADOW.json"
DEFAULT_SOURCE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_readmission_20261018_v1/source"
)
DEFAULT_MODEL = DEFAULT_SOURCE / "gear_sonic_deploy/g1/g1_29dof.xml"
DEFAULT_POLICY_PARAMETERS = (
    DEFAULT_SOURCE
    / "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/policy_parameters.hpp"
)
DEFAULT_SIM_CONFIG = DEFAULT_SOURCE / "gear_sonic/config/manager_env/base_env.yaml"


def merge_planner_replan(
    old_qpos_50hz: Any,
    generated_qpos_50hz: Any,
    *,
    current_frame: int,
    generation_frame: int,
    blend_ticks: int = REPLAN_BLEND_TICKS,
) -> Any:
    """Mirror ``CurrentFrameAdvancement`` rebase and eight-frame cross-fade."""

    import numpy as np

    old = np.asarray(old_qpos_50hz, dtype=np.float64)
    generated = np.asarray(generated_qpos_50hz, dtype=np.float64)
    if (
        old.ndim != 2
        or generated.ndim != 2
        or old.shape[1:] != (36,)
        or generated.shape[1:] != (36,)
        or not np.isfinite(old).all()
        or not np.isfinite(generated).all()
    ):
        raise ValueError("planner replan inputs must be finite [N,36] arrays")
    if not 0 <= current_frame < old.shape[0]:
        raise ValueError("current planner frame is outside the old motion")
    if generation_frame < 0 or blend_ticks <= 0:
        raise ValueError("generation frame and blend width must be valid")
    output_count = generation_frame - current_frame + generated.shape[0]
    if output_count <= 0:
        raise ValueError("late planner result has no remaining frames")

    result = np.empty((output_count, 36), dtype=np.float64)
    blend_start = max(0, generation_frame - current_frame)
    for frame in range(output_count):
        old_index = min(max(frame + current_frame, 0), old.shape[0] - 1)
        new_index = min(
            max(frame + current_frame - generation_frame, 0),
            generated.shape[0] - 1,
        )
        weight_new = min(1.0, max(0.0, (frame - blend_start) / blend_ticks))
        weight_old = 1.0 - weight_new
        result[frame, :3] = (
            weight_old * old[old_index, :3] + weight_new * generated[new_index, :3]
        )
        result[frame, 3:7] = _quaternion_slerp(
            old[old_index, 3:7], generated[new_index, 3:7], weight_new
        )
        result[frame, 7:] = (
            weight_old * old[old_index, 7:] + weight_new * generated[new_index, 7:]
        )
    return result


def _planner_walk(planner: Any, context: Any) -> tuple[Any, dict[str, Any]]:
    raw, count, timing = _run_once(
        planner,
        build_planner_inputs(
            context,
            mode=2,
            movement_direction=(1.0, 0.0, 0.0),
            facing_direction=(1.0, 0.0, 0.0),
            random_seed=DEFAULT_RANDOM_SEED,
        ),
    )
    valid, _, metrics = validate_planner_outputs(raw, count)
    return resample_qpos_50hz(valid), {
        **metrics,
        "inference_seconds": timing,
    }


def build_long_planner_reference(planner: Any) -> tuple[Any, dict[str, Any]]:
    """Create 175 walking frames using the official two-frame replan seam."""

    import numpy as np

    idle_raw, idle_count, idle_timing = _run_once(
        planner,
        build_planner_inputs(
            initialize_context(), mode=0, random_seed=DEFAULT_RANDOM_SEED
        ),
    )
    idle_valid, _, idle_metrics = validate_planner_outputs(idle_raw, idle_count)
    idle = resample_qpos_50hz(idle_valid)
    current, initial_metrics = _planner_walk(planner, context_from_motion_50hz(idle))
    consumed = []
    calls = [
        {"kind": "idle", **idle_metrics, "inference_seconds": idle_timing},
        {"kind": "walk_initial", **initial_metrics},
    ]
    for replan_index in range(2):
        generation_frame = REPLAN_AFTER_TICKS + 2
        context = context_from_motion_50hz(current, generation_frame=generation_frame)
        generated, metrics = _planner_walk(planner, context)
        consumed.append(current[:REPLAN_AFTER_TICKS].copy())
        current = merge_planner_replan(
            current,
            generated,
            current_frame=REPLAN_AFTER_TICKS,
            generation_frame=generation_frame,
        )
        calls.append({"kind": f"walk_replan_{replan_index + 1}", **metrics})
    reference = np.concatenate([*consumed, current], axis=0)
    if reference.shape[0] < CONTROL_TICKS + G1_LOOKAHEAD_TICKS:
        raise RuntimeError("planner replans did not cover the dynamic shadow window")
    return reference, {
        "forward_calls": len(calls),
        "calls": calls,
        "frame_count_50hz": int(reference.shape[0]),
        "qpos_sha256": _array_sha256(reference),
        "horizontal_displacement_m": float(
            np.linalg.norm(reference[-1, :2] - reference[0, :2])
        ),
        "replan_count": 2,
        "replan_current_frame": REPLAN_AFTER_TICKS,
        "generation_lookahead_ticks": 2,
        "blend_ticks": REPLAN_BLEND_TICKS,
    }


def _reference_velocities(reference_qpos: Any) -> Any:
    import numpy as np

    qpos = np.asarray(reference_qpos, dtype=np.float64)
    velocities = np.empty((qpos.shape[0], 29), dtype=np.float64)
    velocities[:-1] = np.diff(qpos[:, 7:], axis=0) / CONTROL_DT_S
    velocities[-1] = velocities[-2]
    return velocities


def build_dynamic_g1_encoder_blocks(
    reference_qpos_50hz: Any,
    reference_velocity_mujoco_rad_s: Any,
    index: int,
    *,
    initial_robot_quaternion_wxyz: Any,
    current_robot_quaternion_wxyz: Any,
) -> dict[str, Any]:
    """Build official g1-mode reference blocks against the real robot heading."""

    import numpy as np

    reference = np.asarray(reference_qpos_50hz, dtype=np.float64)
    velocities = np.asarray(reference_velocity_mujoco_rad_s, dtype=np.float64)
    if (
        reference.ndim != 2
        or reference.shape[1] != 36
        or velocities.shape != (reference.shape[0], 29)
        or index < 0
        or index + G1_LOOKAHEAD_TICKS >= reference.shape[0]
        or not np.isfinite(reference).all()
        or not np.isfinite(velocities).all()
    ):
        raise ValueError("dynamic encoder requires a complete finite reference window")
    blocks = {
        block.name: np.zeros(block.dimension, dtype=np.float64)
        for block in ENCODER_BLOCKS
    }
    future = index + np.arange(G1_FUTURE_FRAMES) * G1_FUTURE_STEP
    blocks["encoder_mode_4"] = np.zeros(4, dtype=np.float64)
    blocks["motion_joint_positions_10frame_step5"] = reorder_mujoco_to_isaaclab(
        reference[future, 7:]
    ).reshape(-1)
    blocks["motion_joint_velocities_10frame_step5"] = reorder_mujoco_to_isaaclab(
        velocities[future]
    ).reshape(-1)

    delta_heading = _quat_multiply(
        _heading_quaternion(initial_robot_quaternion_wxyz),
        _quat_conjugate(_heading_quaternion(reference[0, 3:7])),
    )
    current_heading_inv = _quat_conjugate(
        _heading_quaternion(current_robot_quaternion_wxyz)
    )
    anchors = []
    for future_index in future:
        aligned_reference = _quat_multiply(delta_heading, reference[future_index, 3:7])
        anchors.append(
            _rotation_6d_rowwise(_quat_multiply(current_heading_inv, aligned_reference))
        )
    blocks["motion_anchor_orientation_heading_10frame_step5"] = np.asarray(
        anchors
    ).reshape(-1)
    return blocks


def official_control_arrays() -> dict[str, tuple[float, ...]]:
    """Reproduce the official motor armature, gain, and effort arrays."""

    armature_multipliers = [1.0] * 29
    for index in (4, 5, 10, 11, 13, 14):
        armature_multipliers[index] = 2.0
    armatures = []
    stiffness = []
    damping = []
    effort = []
    for motor_type, multiplier in zip(
        ACTION_MOTOR_TYPES, armature_multipliers, strict=True
    ):
        parameters = MOTOR_PARAMETERS[motor_type]
        armature = parameters["armature"] * multiplier
        armatures.append(armature)
        stiffness.append(armature * NATURAL_FREQUENCY * NATURAL_FREQUENCY)
        damping.append(2.0 * 2.0 * armature * NATURAL_FREQUENCY)
        effort.append(parameters["effort_limit"])
    return {
        "armature": tuple(armatures),
        "kp": tuple(stiffness),
        "kd": tuple(damping),
        "effort_limit": tuple(effort),
    }


def stripped_official_model_xml(model_path: Path) -> tuple[bytes, dict[str, int]]:
    """Remove unresolved LFS meshes while retaining primitive collision geometry."""

    root = ET.parse(model_path).getroot()
    mesh_assets_removed = 0
    mesh_geometries_removed = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "mesh":
                parent.remove(child)
                mesh_assets_removed += 1
            elif child.tag == "geom" and child.attrib.get("type") == "mesh":
                parent.remove(child)
                mesh_geometries_removed += 1
    payload = ET.tostring(root, encoding="utf-8")
    return payload, {
        "mesh_assets_removed": mesh_assets_removed,
        "mesh_geometries_removed": mesh_geometries_removed,
    }


def _validated_prior_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    stored = report.get("content_sha256_excluding_this_field")
    content = {
        key: value
        for key, value in report.items()
        if key != "content_sha256_excluding_this_field"
    }
    if stored != canonical_sha256(content):
        raise RuntimeError("full zero-physics shadow content hash mismatch")
    if report.get("gates", {}).get("official_planner_to_policy_seam_ready") is not True:
        raise RuntimeError("full zero-physics shadow is not admitted")
    return report


def _model_ids(mujoco: Any, model: Any) -> dict[str, Any]:
    import numpy as np

    joint_ids = np.asarray(
        [
            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            for name in SONIC_BODY_JOINT_ORDER
        ],
        dtype=np.int32,
    )
    actuator_ids = np.asarray(
        [
            mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
            for name in SONIC_BODY_JOINT_ORDER
        ],
        dtype=np.int32,
    )
    if (joint_ids < 0).any() or (actuator_ids < 0).any():
        raise RuntimeError("official model is missing a SONIC body joint or actuator")
    qpos_ids = model.jnt_qposadr[joint_ids].copy()
    dof_ids = model.jnt_dofadr[joint_ids].copy()
    if len(set(actuator_ids.tolist())) != 29:
        raise RuntimeError("official model body actuator mapping is not one-to-one")
    gyro_id = mujoco.mj_name2id(
        model, mujoco.mjtObj.mjOBJ_SENSOR, "imu-angular-velocity"
    )
    if gyro_id < 0 or int(model.sensor_dim[gyro_id]) != 3:
        raise RuntimeError("official model IMU gyro is missing")
    gyro_adr = int(model.sensor_adr[gyro_id])
    return {
        "joint_ids": joint_ids,
        "actuator_ids": actuator_ids,
        "qpos_ids": qpos_ids,
        "dof_ids": dof_ids,
        "gyro_slice": slice(gyro_adr, gyro_adr + 3),
    }


def _mapping_inputs(
    positions: Any,
    velocities: Any,
    quaternions: Any,
    angular_velocities: Any,
) -> MappingInputs:
    import numpy as np

    rows = int(np.asarray(positions).shape[0])
    return MappingInputs(
        times_s=np.arange(rows, dtype=np.float64) * CONTROL_DT_S,
        body_position_mujoco_rad=np.asarray(positions, dtype=np.float64),
        body_velocity_mujoco_rad_s=np.asarray(velocities, dtype=np.float64),
        base_quaternion_wxyz=np.asarray(quaternions, dtype=np.float64),
        base_angular_velocity_rad_s=np.asarray(angular_velocities, dtype=np.float64),
        source_targets_mujoco_rad=np.repeat(
            np.asarray(DEFAULT_ANGLES, dtype=np.float64)[None, :], rows, axis=0
        ),
        phase_events=({"sim_time_s": 0.0, "phase": "official_planner_walk"},),
        source_model_joint_order=(),
        source_actuator_order=(),
    )


def _contact_metrics(mujoco: Any, model: Any, data: Any) -> tuple[float, float]:
    import numpy as np

    penetration = 0.0
    force_max = 0.0
    force = np.zeros(6, dtype=np.float64)
    for index in range(data.ncon):
        penetration = max(penetration, max(0.0, -float(data.contact[index].dist)))
        mujoco.mj_contactForce(model, data, index, force)
        force_max = max(force_max, float(np.linalg.norm(force[:3])))
    return penetration, force_max


def _longest_true_run(values: Sequence[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _json_float(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def run_dynamic_shadow(
    *,
    bundle_root: Path = DEFAULT_BUNDLE,
    full_shadow_path: Path = DEFAULT_FULL_SHADOW,
    model_path: Path = DEFAULT_MODEL,
    trace_output: Path = DEFAULT_TRACE_OUTPUT,
) -> dict[str, Any]:
    import mujoco
    import numpy as np
    import onnxruntime as ort

    started = time.monotonic()
    _validated_prior_report(full_shadow_path)
    planner_path = bundle_root / "planner/target_vel/V2/planner_sonic.onnx"
    encoder_path = bundle_root / "policy/sonic_v1_1/model_encoder.onnx"
    decoder_path = bundle_root / "policy/sonic_v1_1/model_decoder.onnx"
    observation_path = bundle_root / "policy/sonic_v1_1/observation_config.yaml"
    expected = {
        planner_path: EXPECTED_PLANNER_SHA256,
        encoder_path: EXPECTED_ENCODER_SHA256,
        decoder_path: EXPECTED_DECODER_SHA256,
        observation_path: EXPECTED_OBSERVATION_CONFIG_SHA256,
    }
    for path, digest in expected.items():
        if sha256_file(path) != digest:
            raise RuntimeError(f"official model/config hash mismatch: {path}")
    layout = parse_v11_config_order(observation_path)
    if not layout["policy_order_matches"] or not layout["encoder_order_matches"]:
        raise RuntimeError("SONIC observation config order mismatch")

    planner = _make_session(planner_path)
    reference, planner_metrics = build_long_planner_reference(planner)
    del planner
    reference_velocities = _reference_velocities(reference)

    xml_payload, strip_metrics = stripped_official_model_xml(model_path)
    model = mujoco.MjModel.from_xml_string(xml_payload.decode("utf-8"))
    model.opt.timestep = SIMULATION_DT_S
    if model.nq != 36 or model.nv != 35 or model.nu != 29:
        raise RuntimeError(
            "stripped official model does not retain the 29-DoF contract"
        )
    ids = _model_ids(mujoco, model)
    controls = official_control_arrays()
    armature = np.asarray(controls["armature"], dtype=np.float64)
    kp = np.asarray(controls["kp"], dtype=np.float64)
    kd = np.asarray(controls["kd"], dtype=np.float64)
    effort = np.asarray(controls["effort_limit"], dtype=np.float64)
    model.dof_armature[ids["dof_ids"]] = armature
    lower = model.jnt_range[ids["joint_ids"], 0].copy()
    upper = model.jnt_range[ids["joint_ids"], 1].copy()
    defaults = np.asarray(DEFAULT_ANGLES, dtype=np.float64)
    if not bool(((defaults >= lower) & (defaults <= upper)).all()):
        raise RuntimeError("official default angles fall outside official joint ranges")

    data = mujoco.MjData(model)
    data.qpos[ids["qpos_ids"]] = defaults
    data.qvel[:] = 0.0
    mujoco.mj_forward(model, data)
    initial_robot_quaternion = data.qpos[3:7].copy()
    encoder = _make_session(encoder_path)
    decoder = _make_session(decoder_path)

    positions: list[Any] = []
    velocities: list[Any] = []
    quaternions: list[Any] = []
    angular_velocities: list[Any] = []
    raw_actions = np.zeros((CONTROL_TICKS, 29), dtype=np.float32)
    candidates = np.zeros((CONTROL_TICKS, 29), dtype=np.float64)
    candidate_safe: list[bool] = []
    trace: list[dict[str, Any]] = []
    inference_seconds: list[float] = []
    hashes = {
        name: hashlib.sha256()
        for name in ("encoder_inputs", "tokens", "decoder_inputs", "raw_actions")
    }
    physical = {
        "minimum_pelvis_height_m": float(data.qpos[2]),
        "minimum_pelvis_up_component": 1.0,
        "maximum_penetration_m": 0.0,
        "maximum_contact_force_n": 0.0,
        "maximum_abs_joint_velocity_rad_s": 0.0,
        "maximum_abs_baseline_torque_nm": 0.0,
        "baseline_torque_saturation_count": 0,
        "nonfinite_steps": 0,
        "external_wrench_violations": 0,
    }
    maximum_candidate_step = 0.0
    maximum_target_to_state = 0.0
    maximum_target_to_reference = 0.0
    maximum_reference_to_state = 0.0
    consecutive = 0
    maximum_consecutive = 0

    for tick in range(CONTROL_TICKS):
        position = data.qpos[ids["qpos_ids"]].copy()
        velocity = data.qvel[ids["dof_ids"]].copy()
        quaternion = data.qpos[3:7].copy()
        angular_velocity = data.sensordata[ids["gyro_slice"]].copy()
        positions.append(position)
        velocities.append(velocity)
        quaternions.append(quaternion)
        angular_velocities.append(angular_velocity)
        inputs = _mapping_inputs(positions, velocities, quaternions, angular_velocities)

        encoder_values = ENCODER_ASSEMBLER.assemble(
            build_dynamic_g1_encoder_blocks(
                reference,
                reference_velocities,
                tick,
                initial_robot_quaternion_wxyz=initial_robot_quaternion,
                current_robot_quaternion_wxyz=quaternion,
            )
        )
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        inference_started = time.perf_counter()
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_values = DECODER_ASSEMBLER.assemble(
            build_decoder_blocks(
                inputs,
                tick,
                token_state=token,
                logged_last_actions_isaaclab=raw_actions[: tick + 1],
                prepared_state=prepare_decoder_state(inputs),
            )
        )
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        action = decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[0]
        inference_seconds.append(time.perf_counter() - inference_started)
        action = np.asarray(action, dtype=np.float32).reshape(-1)
        if action.shape != (29,) or not np.isfinite(action).all():
            raise RuntimeError("SONIC decoder returned an invalid action")
        raw_actions[tick] = action
        candidate = np.asarray(
            body_joint_target_from_raw_action(
                action,
                phase="official_planner_walk_dynamic_shadow",
                sim_time_s=tick * CONTROL_DT_S,
            ).position_target_rad,
            dtype=np.float64,
        )
        candidates[tick] = candidate
        previous = defaults if tick == 0 else candidates[tick - 1]
        step = float(np.max(np.abs(candidate - previous)))
        finite = bool(np.isfinite(candidate).all())
        in_range = bool(((candidate >= lower) & (candidate <= upper)).all())
        slew_safe = step <= MAX_CANDIDATE_STEP_RAD
        safe = finite and in_range and slew_safe
        candidate_safe.append(safe)
        consecutive = consecutive + 1 if safe else 0
        maximum_consecutive = max(maximum_consecutive, consecutive)
        maximum_candidate_step = max(maximum_candidate_step, step)
        maximum_target_to_state = max(
            maximum_target_to_state, float(np.max(np.abs(candidate - position)))
        )
        maximum_target_to_reference = max(
            maximum_target_to_reference,
            float(np.max(np.abs(candidate - reference[tick, 7:]))),
        )
        maximum_reference_to_state = max(
            maximum_reference_to_state,
            float(np.max(np.abs(reference[tick, 7:] - position))),
        )

        hashes["encoder_inputs"].update(encoder_input.tobytes())
        hashes["tokens"].update(np.asarray(token, dtype=np.float32).tobytes())
        hashes["decoder_inputs"].update(decoder_input.tobytes())
        hashes["raw_actions"].update(action.tobytes())

        tick_penetration = 0.0
        tick_force = 0.0
        for _ in range(CONTROL_DECIMATION):
            current_position = data.qpos[ids["qpos_ids"]]
            current_velocity = data.qvel[ids["dof_ids"]]
            unclipped_torque = (
                kp * (defaults - current_position) - kd * current_velocity
            )
            torque = np.clip(unclipped_torque, -effort, effort)
            physical["baseline_torque_saturation_count"] += int(
                np.count_nonzero(np.abs(unclipped_torque) > effort)
            )
            physical["maximum_abs_baseline_torque_nm"] = max(
                physical["maximum_abs_baseline_torque_nm"],
                float(np.max(np.abs(torque))),
            )
            data.ctrl[ids["actuator_ids"]] = torque
            mujoco.mj_step(model, data)
            finite_state = bool(
                np.isfinite(data.qpos).all()
                and np.isfinite(data.qvel).all()
                and np.isfinite(data.ctrl).all()
            )
            if not finite_state:
                physical["nonfinite_steps"] += 1
                raise RuntimeError("MuJoCo produced a nonfinite state")
            if np.any(data.qfrc_applied) or np.any(data.xfrc_applied):
                physical["external_wrench_violations"] += 1
            pelvis = float(data.qpos[2])
            base_quaternion = data.qpos[3:7]
            up = float(1.0 - 2.0 * (base_quaternion[1] ** 2 + base_quaternion[2] ** 2))
            penetration, contact_force = _contact_metrics(mujoco, model, data)
            tick_penetration = max(tick_penetration, penetration)
            tick_force = max(tick_force, contact_force)
            physical["minimum_pelvis_height_m"] = min(
                physical["minimum_pelvis_height_m"], pelvis
            )
            physical["minimum_pelvis_up_component"] = min(
                physical["minimum_pelvis_up_component"], up
            )
            physical["maximum_penetration_m"] = max(
                physical["maximum_penetration_m"], penetration
            )
            physical["maximum_contact_force_n"] = max(
                physical["maximum_contact_force_n"], contact_force
            )
            physical["maximum_abs_joint_velocity_rad_s"] = max(
                physical["maximum_abs_joint_velocity_rad_s"],
                float(np.max(np.abs(data.qvel[ids["dof_ids"]]))),
            )

        trace.append(
            {
                "control_tick": tick,
                "sim_time_s_after_step": float(data.time),
                "pelvis_height_m": float(data.qpos[2]),
                "pelvis_up_component": float(
                    1.0 - 2.0 * (data.qpos[4] ** 2 + data.qpos[5] ** 2)
                ),
                "candidate_finite": finite,
                "candidate_in_official_joint_range": in_range,
                "candidate_step_safe": slew_safe,
                "candidate_safe": safe,
                "consecutive_candidate_safe_ticks": consecutive,
                "candidate_max_step_rad": step,
                "candidate_to_actual_max_abs_rad": float(
                    np.max(np.abs(candidate - position))
                ),
                "reference_to_actual_max_abs_rad": float(
                    np.max(np.abs(reference[tick, 7:] - position))
                ),
                "tick_maximum_penetration_m": tick_penetration,
                "tick_maximum_contact_force_n": tick_force,
                "sonic_candidate_consumed_by_physics": False,
                "physics_command_source": "official_fixed_standing_pd_baseline",
            }
        )

    trace_document = {
        "schema": TRACE_SCHEMA,
        "control_ticks": CONTROL_TICKS,
        "physics_steps": PHYSICS_STEPS,
        "records": trace,
    }
    trace_document["content_sha256_excluding_this_field"] = canonical_sha256(
        trace_document
    )
    write_json_atomic(trace_output, trace_document)

    physical_gates = {
        "all_states_finite": physical["nonfinite_steps"] == 0,
        "no_external_wrench": physical["external_wrench_violations"] == 0,
        "pelvis_height": physical["minimum_pelvis_height_m"] >= MIN_PELVIS_HEIGHT_M,
        "upright": physical["minimum_pelvis_up_component"] >= MIN_PELVIS_UP_COMPONENT,
        "penetration": physical["maximum_penetration_m"] <= MAX_PENETRATION_M,
        "contact_force": physical["maximum_contact_force_n"] <= MAX_CONTACT_FORCE_N,
    }
    command_gates = {
        "all_candidates_finite": bool(np.isfinite(candidates).all()),
        "all_candidates_in_official_joint_range": bool(
            ((candidates >= lower) & (candidates <= upper)).all()
        ),
        "all_candidate_steps_within_frozen_limit": maximum_candidate_step
        <= MAX_CANDIDATE_STEP_RAD,
        "continuous_50_tick_candidate_window": maximum_consecutive
        >= QUALIFICATION_TICKS,
    }
    ready = all(physical_gates.values()) and all(command_gates.values())
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "passed" if ready else "diagnostic",
        "purpose": (
            "real-state MuJoCo shadow admission for official planner plus SONIC "
            "v1.1 body chain"
        ),
        "inputs": {
            "full_zero_physics_shadow": _file_binding(full_shadow_path),
            "planner_model": _file_binding(planner_path),
            "encoder_model": _file_binding(encoder_path),
            "decoder_model": _file_binding(decoder_path),
            "observation_config": _file_binding(observation_path),
            "observation_layout": layout,
            "official_robot_model": _file_binding(model_path),
            "official_policy_parameters": _file_binding(DEFAULT_POLICY_PARAMETERS),
            "official_simulation_config": _file_binding(DEFAULT_SIM_CONFIG),
        },
        "planner_reference": planner_metrics,
        "simulator_model": {
            "source": "official SONIC g1_29dof.xml",
            "derived_xml_sha256": hashlib.sha256(xml_payload).hexdigest(),
            **strip_metrics,
            "retained_primitive_geometry_count": int(model.ngeom),
            "nq": int(model.nq),
            "nv": int(model.nv),
            "nu": int(model.nu),
            "simulation_dt_s": SIMULATION_DT_S,
            "control_dt_s": CONTROL_DT_S,
            "control_decimation": CONTROL_DECIMATION,
            "collision_fidelity": (
                "limited: official mesh files are Git-LFS pointers; official "
                "inertias, foot spheres, arm cylinders, and floor are retained"
            ),
        },
        "baseline_controller": {
            "source": "official policy_parameters.hpp motor constants",
            "target": "fixed official default standing angles",
            "source_a_body_command_used": False,
            "kp": list(controls["kp"]),
            "kd": list(controls["kd"]),
            "armature": list(controls["armature"]),
            "effort_limit_nm": list(controls["effort_limit"]),
            "torque_clipped_only_to_official_effort_limits": True,
        },
        "policy_shadow": {
            "control_ticks": CONTROL_TICKS,
            "encoder_forward_calls": CONTROL_TICKS,
            "decoder_forward_calls": CONTROL_TICKS,
            "encoder_input_sha256": hashes["encoder_inputs"].hexdigest(),
            "encoder_tokens_sha256": hashes["tokens"].hexdigest(),
            "decoder_input_sha256": hashes["decoder_inputs"].hexdigest(),
            "raw_actions_sha256": hashes["raw_actions"].hexdigest(),
            "targets_sha256": _array_sha256(candidates),
            "maximum_candidate_step_rad": maximum_candidate_step,
            "maximum_target_to_actual_state_delta_rad": maximum_target_to_state,
            "maximum_target_to_reference_delta_rad": maximum_target_to_reference,
            "maximum_reference_to_actual_state_delta_rad": maximum_reference_to_state,
            "safe_candidate_tick_count": int(sum(candidate_safe)),
            "longest_continuous_safe_candidate_run_ticks": maximum_consecutive,
            "mean_encoder_decoder_seconds": float(np.mean(inference_seconds)),
            "maximum_encoder_decoder_seconds": float(np.max(inference_seconds)),
            "last_action_history": (
                "prior raw SONIC shadow outputs; candidates are counterfactual and "
                "are not consumed by physics"
            ),
        },
        "physical_metrics": {
            key: _json_float(value) if isinstance(value, float) else value
            for key, value in physical.items()
        },
        "command_guard": {
            "official_joint_lower_rad": lower.tolist(),
            "official_joint_upper_rad": upper.tolist(),
            "maximum_50hz_candidate_delta_rad": MAX_CANDIDATE_STEP_RAD,
            "qualification_ticks": QUALIFICATION_TICKS,
            "output_clipping_or_slew_limiting": False,
            "candidate_consumed_by_physics": False,
        },
        "gates": {
            **physical_gates,
            **command_gates,
            "source_a_body_reference_absent": True,
            "source_a_body_command_absent": True,
            "sonic_candidate_actuator_writes_zero": True,
            "sonic_only_physics_smoke_admission_ready": ready,
        },
        "execution_limits": {
            "physics_executed": True,
            "physics_steps": PHYSICS_STEPS,
            "baseline_control_updates": PHYSICS_STEPS,
            "sonic_candidate_actuator_writes": 0,
            "source_a_body_reference_used": False,
            "source_a_body_command_used": False,
            "training_executed": False,
            "rendering_executed": False,
            "network_used": False,
            "downloads": 0,
        },
        "dex3_boundary": {
            "model_body_actuator_count": 29,
            "dex3_actuators_present": False,
            "dex3_write_set_empty": True,
            "hand_control_validated": False,
            "meaning": (
                "SONIC v1.1 controls only the 29-DoF body; Dex3 task/hand "
                "integration remains a later independent seam"
            ),
        },
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "mujoco": mujoco.__version__,
            "onnxruntime": ort.__version__,
            "providers": encoder.get_providers(),
            "wall_seconds": time.monotonic() - started,
            "maximum_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "trace": _file_binding(trace_output),
        "capability_boundary": {
            "dynamic_real_state_shadow_validated": ready,
            "sonic_candidate_entered_physics": False,
            "sonic_only_physics_smoke_executed": False,
            "full_mesh_collision_validated": False,
            "task_success_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
        "next_step": (
            "Only if every gate passes: run one separate SONIC-only body physics "
            "smoke capped at 100 active 50 Hz ticks, with the same fail-closed "
            "joint, slew, pelvis, upright, penetration, and force limits."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--full-shadow", type=Path, default=DEFAULT_FULL_SHADOW)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--trace-output", type=Path, default=DEFAULT_TRACE_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    report = run_dynamic_shadow(
        bundle_root=arguments.bundle_root,
        full_shadow_path=arguments.full_shadow,
        model_path=arguments.model,
        trace_output=arguments.trace_output,
    )
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["gates"]["sonic_only_physics_smoke_admission_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
