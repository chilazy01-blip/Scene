"""Run a causal, non-actuating SONIC v1.1 hold-reference CPU shadow.

At tick ``t`` the encoder reference is a one-frame snapshot assembled only
from values available at ``t``: the current Source-A 29-body command and the
current measured base orientation.  The snapshot follows the official paused
``g1`` observation semantics: repeat the current joint position and anchor for
all ten reference frames and set all reference velocities to zero.

The decoder uses measured state history through ``t`` and SONIC's own prior
raw actions.  No future row is read, physics is never advanced, and this module
contains no actuator write path.  The result is evidence for a causal reference
seam on frozen data, not an independent online controller.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    DEFAULT_S3_EPISODE,
    DEFAULT_SONIC_RUN,
    DEFAULT_SOURCE_A,
    G1_FUTURE_FRAMES,
    G1_FUTURE_STEP,
    G1_REQUIRED_ENCODER_BLOCKS,
    HISTORY_FRAMES,
    MUJOCO_TO_ISAACLAB,
    MappingInputs,
    _file_binding,
    _heading_quaternion,
    _phase_at,
    _quat_conjugate,
    _quat_multiply,
    _rotation_6d_rowwise,
    _update_float32_hash,
    build_decoder_blocks,
    inspect_bundled_references,
    load_mapping_inputs,
    prepare_decoder_state,
    reorder_mujoco_to_isaaclab,
)
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    DECODER_BLOCKS,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    ENCODER_BLOCKS,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import BodyJointTarget, SONIC_BODY_JOINT_ORDER, SonicShadowBridge


SCHEMA = "sonic-causal-hold-shadow/v1"
REFERENCE_SEMANTICS = "current_tick_source_a_command_paused_hold_snapshot"


def build_causal_hold_encoder_blocks(
    inputs: MappingInputs, index: int
) -> dict[str, Any]:
    """Build the official g1-mode blocks without reading beyond ``index``."""

    import numpy as np

    if index < 0 or index >= inputs.sample_count:
        raise ValueError("causal reference index is invalid")
    blocks = {
        block.name: np.zeros(block.dimension, dtype=np.float64)
        for block in ENCODER_BLOCKS
    }

    current_target = reorder_mujoco_to_isaaclab(inputs.source_targets_mujoco_rad[index])
    held_positions = np.repeat(current_target[None, :], G1_FUTURE_FRAMES, axis=0)
    held_velocities = np.zeros_like(held_positions)

    current_root = inputs.base_quaternion_wxyz[index]
    current_robot_heading = _heading_quaternion(current_root)
    current_reference_heading_inv = _quat_conjugate(_heading_quaternion(current_root))
    apply_delta_heading = _quat_multiply(
        current_robot_heading, current_reference_heading_inv
    )
    current_heading_inv = _quat_conjugate(current_robot_heading)
    aligned_reference = _quat_multiply(apply_delta_heading, current_root)
    held_anchor = _rotation_6d_rowwise(
        _quat_multiply(current_heading_inv, aligned_reference)
    )

    blocks["encoder_mode_4"] = np.asarray([0.0, 0.0, 0.0, 0.0])
    blocks["motion_joint_positions_10frame_step5"] = held_positions.reshape(-1)
    blocks["motion_joint_velocities_10frame_step5"] = held_velocities.reshape(-1)
    blocks["motion_anchor_orientation_heading_10frame_step5"] = np.tile(
        held_anchor, G1_FUTURE_FRAMES
    )
    return blocks


def _prefix(inputs: MappingInputs, end_exclusive: int) -> MappingInputs:
    """Return the same input contract with no row after ``end_exclusive - 1``."""

    return replace(
        inputs,
        times_s=inputs.times_s[:end_exclusive],
        body_position_mujoco_rad=inputs.body_position_mujoco_rad[:end_exclusive],
        body_velocity_mujoco_rad_s=inputs.body_velocity_mujoco_rad_s[:end_exclusive],
        base_quaternion_wxyz=inputs.base_quaternion_wxyz[:end_exclusive],
        base_angular_velocity_rad_s=inputs.base_angular_velocity_rad_s[:end_exclusive],
        source_targets_mujoco_rad=inputs.source_targets_mujoco_rad[:end_exclusive],
    )


def verify_prefix_equivalence(inputs: MappingInputs) -> dict[str, Any]:
    """Prove selected full-stream observations equal prefix-only observations."""

    import numpy as np

    candidates = (0, 1, 8, 9, 10, 1000, inputs.sample_count - 1)
    indices = sorted(
        {index for index in candidates if 0 <= index < inputs.sample_count}
    )
    rows = []
    all_equal = True
    for index in indices:
        prefix = _prefix(inputs, index + 1)
        full_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(build_causal_hold_encoder_blocks(inputs, index)),
            dtype=np.float32,
        )
        prefix_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(build_causal_hold_encoder_blocks(prefix, index)),
            dtype=np.float32,
        )

        action_history = np.zeros((inputs.sample_count, 29), dtype=np.float64)
        action_history[: index + 1] = (
            np.arange(index + 1, dtype=np.float64)[:, None] * 0.001
        )
        token = np.arange(64, dtype=np.float64) * 0.01
        full_decoder = np.asarray(
            DECODER_ASSEMBLER.assemble(
                build_decoder_blocks(
                    inputs,
                    index,
                    token_state=token,
                    logged_last_actions_isaaclab=action_history,
                )
            ),
            dtype=np.float32,
        )
        prefix_decoder = np.asarray(
            DECODER_ASSEMBLER.assemble(
                build_decoder_blocks(
                    prefix,
                    index,
                    token_state=token,
                    logged_last_actions_isaaclab=action_history[: index + 1],
                )
            ),
            dtype=np.float32,
        )
        encoder_equal = bool(np.array_equal(full_encoder, prefix_encoder))
        decoder_equal = bool(np.array_equal(full_decoder, prefix_decoder))
        all_equal = all_equal and encoder_equal and decoder_equal
        rows.append(
            {
                "sample_index": index,
                "prefix_sample_count": index + 1,
                "encoder_equal": encoder_equal,
                "decoder_equal": decoder_equal,
                "encoder_sha256": hashlib.sha256(full_encoder.tobytes()).hexdigest(),
                "decoder_sha256": hashlib.sha256(full_decoder.tobytes()).hexdigest(),
            }
        )
    return {
        "method": "full_stream_vs_physically_truncated_prefix_exact_float32_equality",
        "probe_count": len(rows),
        "all_equal": all_equal,
        "probes": rows,
    }


def inspect_official_paused_semantics(sonic_root: Path) -> dict[str, Any]:
    controller_path = (
        sonic_root / "source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/"
        "g1_deploy_onnx_ref.cpp"
    )
    config_path = sonic_root / "weights/sonic_v1_1/observation_config.yaml"
    controller = controller_path.read_text(encoding="utf-8", errors="replace")
    config = config_path.read_text(encoding="utf-8", errors="replace")
    anchor = controller.split("bool GatherMotionAnchorOrientationMutiFrame", 1)[
        1
    ].split("bool GatherHeadingDiffRobotRef", 1)[0]
    positions = controller.split("bool GatherMotionJointPositionsMultiFrame", 1)[
        1
    ].split("bool GatherMotionJointVelocitiesMultiFrame", 1)[0]
    velocities = controller.split("bool GatherMotionJointVelocitiesMultiFrame", 1)[
        1
    ].split("bool GatherMotionSmplJointsMultiFrame", 1)[0]
    markers = {
        "g1_mode_declared": all(
            marker in config
            for marker in (
                'name: "g1"',
                "mode_id: 0",
                *G1_REQUIRED_ENCODER_BLOCKS,
            )
        ),
        "paused_positions_hold_current_frame": (
            "if (operator_state.play)" in positions
            and "target_frame += frame_idx * step_size" in positions
        ),
        "paused_velocities_are_zero": (
            "if (operator_state.play)" in velocities
            and velocities.count("std::fill_n") >= 2
            and velocities.count("0.0") >= 2
        ),
        "paused_anchor_holds_current_frame": (
            "if (operator_state.play)" in anchor
            and "target_frame += frame_idx * step_size" in anchor
        ),
        "heading_anchor_uses_robot_heading": (
            "left_quat = calc_heading_quat_d(base_quat)" in anchor
        ),
        "anchor_rotation_is_rowwise_first_two_columns": (
            "rotation_matrix[0][0], rotation_matrix[0][1]" in anchor
            and "rotation_matrix[2][0], rotation_matrix[2][1]" in anchor
        ),
    }
    return {
        "controller": _file_binding(controller_path),
        "observation_config": _file_binding(config_path),
        "markers": markers,
        "all_markers_match": all(markers.values()),
    }


def _mapping_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    encoder_rows = []
    causal_sources = {
        "encoder_mode_4": "explicit current-tick g1 mode_id=0 constant",
        "motion_joint_positions_10frame_step5": (
            "same-tick Source-A 29-body command repeated ten times per official paused semantics"
        ),
        "motion_joint_velocities_10frame_step5": (
            "ten zero rows per official paused semantics"
        ),
        "motion_anchor_orientation_heading_10frame_step5": (
            "same-tick measured root orientation held ten times and expressed from robot heading"
        ),
    }
    for block in ENCODER_BLOCKS:
        if block.name in causal_sources:
            status = "available_current_tick_only"
            source = causal_sources[block.name]
        else:
            status = "available_official_mode_inactive_zero"
            source = "official g1 mode filtering leaves this block zero"
        encoder_rows.append(
            {
                "name": block.name,
                "dimension": block.dimension,
                "status": status,
                "source": source,
                "latest_row_offset_from_current_tick": 0,
            }
        )

    decoder_sources = {
        "token_state": "same-tick causal encoder output",
        "his_base_angular_velocity_10frame_step1": "measured S3 rows t-9 through t",
        "his_body_joint_positions_10frame_step1": "measured S3 rows t-9 through t",
        "his_body_joint_velocities_10frame_step1": "measured S3 rows t-9 through t",
        "his_last_actions_10frame_step1": "SONIC raw outputs from prior ticks only",
        "his_gravity_dir_10frame_step1": "measured S3 base quaternion rows t-9 through t",
    }
    decoder_rows = [
        {
            "name": block.name,
            "dimension": block.dimension,
            "status": "available_current_or_history_only",
            "source": decoder_sources[block.name],
            "latest_row_offset_from_current_tick": 0,
        }
        for block in DECODER_BLOCKS
    ]
    return encoder_rows, decoder_rows


def run_causal_shadow(
    *,
    inputs: MappingInputs,
    encoder_path: Path,
    decoder_path: Path,
    max_samples: int | None = None,
) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as ort

    requested = inputs.sample_count if max_samples is None else max_samples
    if requested <= 0:
        raise ValueError("max_samples must be positive")
    count = min(inputs.sample_count, requested)

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    encoder = ort.InferenceSession(
        str(encoder_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    decoder = ort.InferenceSession(
        str(decoder_path), sess_options=options, providers=["CPUExecutionProvider"]
    )
    logged_actions = np.zeros((count, 29), dtype=np.float64)
    prepared_decoder_state = prepare_decoder_state(inputs)
    bridge = SonicShadowBridge(SONIC_BODY_JOINT_ORDER)
    hashes = {
        name: hashlib.sha256()
        for name in (
            "encoder_inputs",
            "encoder_tokens",
            "decoder_inputs",
            "raw_actions",
            "scaled_targets",
            "source_targets",
        )
    }
    joint_abs_sum = np.zeros(29, dtype=np.float64)
    joint_sq_sum = np.zeros(29, dtype=np.float64)
    joint_max = np.zeros(29, dtype=np.float64)
    raw_jump_abs_sum = np.zeros(29, dtype=np.float64)
    raw_jump_sq_sum = np.zeros(29, dtype=np.float64)
    raw_jump_max = np.zeros(29, dtype=np.float64)
    target_jump_abs_sum = np.zeros(29, dtype=np.float64)
    target_jump_sq_sum = np.zeros(29, dtype=np.float64)
    target_jump_max = np.zeros(29, dtype=np.float64)
    source_jump_abs_sum = np.zeros(29, dtype=np.float64)
    source_jump_sq_sum = np.zeros(29, dtype=np.float64)
    source_jump_max = np.zeros(29, dtype=np.float64)
    previous_raw: Any | None = None
    previous_target: Any | None = None
    previous_source: Any | None = None
    previous_phase: str | None = None
    previous_time_s: float | None = None
    worst_transitions: dict[str, dict[str, Any]] = {}
    pair_timings_ms = []
    phase_accumulators: dict[str, dict[str, Any]] = {}
    exemplars: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()

    for index in range(count):
        pair_started = time.perf_counter()
        encoder_values = ENCODER_ASSEMBLER.assemble(
            build_causal_hold_encoder_blocks(inputs, index)
        )
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_values = DECODER_ASSEMBLER.assemble(
            build_decoder_blocks(
                inputs,
                index,
                token_state=token,
                logged_last_actions_isaaclab=logged_actions,
                prepared_state=prepared_decoder_state,
            )
        )
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        raw_action = decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[
            0
        ].reshape(-1)
        pair_timings_ms.append((time.perf_counter() - pair_started) * 1000.0)
        if not (
            np.isfinite(encoder_input).all()
            and np.isfinite(token).all()
            and np.isfinite(decoder_input).all()
            and np.isfinite(raw_action).all()
        ):
            raise RuntimeError(f"non-finite causal shadow value at sample {index}")

        if index + 1 < count:
            logged_actions[index + 1] = raw_action
        sim_time_s = float(inputs.times_s[index])
        phase = _phase_at(inputs.phase_events, sim_time_s)
        sonic_target = body_joint_target_from_raw_action(
            raw_action, phase=phase, sim_time_s=sim_time_s
        )
        source_target = BodyJointTarget(
            controller_id="source_a_frozen_s3",
            phase=phase,
            sim_time_s=sim_time_s,
            joint_order=SONIC_BODY_JOINT_ORDER,
            position_target_rad=tuple(inputs.source_targets_mujoco_rad[index]),
        ).validated()
        comparison = bridge.compare(source_target, sonic_target)
        delta = np.asarray(comparison["sonic_minus_source_a_rad"], dtype=np.float64)
        absolute = np.abs(delta)
        joint_abs_sum += absolute
        joint_sq_sum += delta * delta
        joint_max = np.maximum(joint_max, absolute)

        target_values = np.asarray(sonic_target.position_target_rad, dtype=np.float64)
        source_values = np.asarray(source_target.position_target_rad, dtype=np.float64)
        if (
            previous_raw is not None
            and previous_target is not None
            and previous_source is not None
            and previous_phase is not None
            and previous_time_s is not None
        ):
            raw_jump = raw_action.astype(np.float64) - previous_raw
            target_jump = target_values - previous_target
            source_jump = source_values - previous_source
            raw_jump_abs_sum += np.abs(raw_jump)
            raw_jump_sq_sum += raw_jump * raw_jump
            raw_jump_max = np.maximum(raw_jump_max, np.abs(raw_jump))
            target_jump_abs_sum += np.abs(target_jump)
            target_jump_sq_sum += target_jump * target_jump
            target_jump_max = np.maximum(target_jump_max, np.abs(target_jump))
            source_jump_abs_sum += np.abs(source_jump)
            source_jump_sq_sum += source_jump * source_jump
            source_jump_max = np.maximum(source_jump_max, np.abs(source_jump))
            for label, selected_jump in (
                ("raw_action", raw_jump),
                ("scaled_body_target_rad", target_jump),
                ("source_a_target_rad", source_jump),
            ):
                joint_index = int(np.argmax(np.abs(selected_jump)))
                magnitude = float(abs(selected_jump[joint_index]))
                if magnitude > worst_transitions.get(label, {}).get(
                    "max_abs_delta", -1.0
                ):
                    worst_transitions[label] = {
                        "max_abs_delta": magnitude,
                        "signed_delta": float(selected_jump[joint_index]),
                        "joint_index": joint_index,
                        "joint_name": SONIC_BODY_JOINT_ORDER[joint_index],
                        "from_sample_index": index - 1,
                        "to_sample_index": index,
                        "from_sim_time_s": previous_time_s,
                        "to_sim_time_s": sim_time_s,
                        "from_phase": previous_phase,
                        "to_phase": phase,
                        "crosses_phase_boundary": previous_phase != phase,
                        "raw_action_delta_same_joint": float(raw_jump[joint_index]),
                        "scaled_body_target_delta_rad_same_joint": float(
                            target_jump[joint_index]
                        ),
                        "source_a_target_delta_rad_same_joint": float(
                            source_jump[joint_index]
                        ),
                    }
        previous_raw = raw_action.astype(np.float64).copy()
        previous_target = target_values.copy()
        previous_source = source_values.copy()
        previous_phase = phase
        previous_time_s = sim_time_s

        phase_row = phase_accumulators.setdefault(
            phase,
            {"samples": 0, "abs_sum": 0.0, "sq_sum": 0.0, "max_abs": 0.0},
        )
        phase_row["samples"] += 1
        phase_row["abs_sum"] += float(absolute.sum())
        phase_row["sq_sum"] += float(np.square(delta).sum())
        phase_row["max_abs"] = max(phase_row["max_abs"], float(absolute.max()))
        if phase not in exemplars:
            exemplars[phase] = {
                "sample_index": index,
                "comparison": comparison,
                "encoder_input_sha256": hashlib.sha256(
                    encoder_input.tobytes()
                ).hexdigest(),
                "decoder_input_sha256": hashlib.sha256(
                    decoder_input.tobytes()
                ).hexdigest(),
                "raw_action_sha256": hashlib.sha256(
                    np.asarray(raw_action, dtype=np.float32).tobytes()
                ).hexdigest(),
            }

        _update_float32_hash(hashes["encoder_inputs"], encoder_input)
        _update_float32_hash(hashes["encoder_tokens"], token)
        _update_float32_hash(hashes["decoder_inputs"], decoder_input)
        _update_float32_hash(hashes["raw_actions"], raw_action)
        _update_float32_hash(hashes["scaled_targets"], target_values)
        _update_float32_hash(
            hashes["source_targets"], source_target.position_target_rad
        )

    elapsed = time.perf_counter() - started
    phase_metrics = {}
    for phase, row in phase_accumulators.items():
        values = row["samples"] * 29
        phase_metrics[phase] = {
            "samples": row["samples"],
            "max_abs_target_delta_rad": row["max_abs"],
            "mean_abs_target_delta_rad": row["abs_sum"] / values,
            "rms_target_delta_rad": math.sqrt(row["sq_sum"] / values),
        }
    timing = np.asarray(pair_timings_ms, dtype=np.float64)
    transition_count = max(0, count - 1)

    def continuity(
        abs_sum: Any, sq_sum: Any, maximum: Any, *, label: str
    ) -> dict[str, Any]:
        if transition_count == 0:
            return {
                "transition_count": 0,
                "available": False,
            }
        return {
            "transition_count": transition_count,
            "available": True,
            "per_joint_mean_abs_delta": (abs_sum / transition_count).tolist(),
            "per_joint_rms_delta": np.sqrt(sq_sum / transition_count).tolist(),
            "per_joint_max_abs_delta": maximum.tolist(),
            "mean_abs_delta": float(abs_sum.sum() / (transition_count * 29)),
            "rms_delta": float(math.sqrt(sq_sum.sum() / (transition_count * 29))),
            "max_abs_delta": float(maximum.max()),
            "worst_transition": worst_transitions[label],
        }

    return {
        "status": "executed_non_actuating",
        "provider": "CPUExecutionProvider",
        "onnxruntime_version": ort.__version__,
        "reference_mode": "g1_mode_id_0_paused_hold_snapshot",
        "reference_semantics": REFERENCE_SEMANTICS,
        "reference_dependency": "same_tick_source_a_body_command",
        "independent_reference_generator": False,
        "causal_reference_evidence": True,
        "online_runtime_evidence": False,
        "sample_count": count,
        "available_causal_samples": inputs.sample_count,
        "first_sim_time_s": float(inputs.times_s[0]),
        "last_sim_time_s": float(inputs.times_s[count - 1]),
        "model_forwards": count * 2,
        "physics_steps": 0,
        "elapsed_wall_s": elapsed,
        "mean_wall_ms_per_encoder_decoder_pair": elapsed * 1000.0 / count,
        "pair_inference_latency_ms": {
            "minimum": float(timing.min()),
            "p50": float(np.percentile(timing, 50)),
            "p95": float(np.percentile(timing, 95)),
            "p99": float(np.percentile(timing, 99)),
            "maximum": float(timing.max()),
            "note": "Python wall time around encoder and decoder calls; not a hard real-time guarantee",
        },
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "all_outputs_finite": True,
        "stream_hashes_float32_concatenated": {
            name: value.hexdigest() for name, value in hashes.items()
        },
        "aggregate_comparison": {
            "joint_order": list(SONIC_BODY_JOINT_ORDER),
            "per_joint_mean_abs_target_delta_rad": (joint_abs_sum / count).tolist(),
            "per_joint_rms_target_delta_rad": np.sqrt(joint_sq_sum / count).tolist(),
            "per_joint_max_abs_target_delta_rad": joint_max.tolist(),
            "mean_abs_target_delta_rad": float(joint_abs_sum.sum() / (count * 29)),
            "rms_target_delta_rad": float(math.sqrt(joint_sq_sum.sum() / (count * 29))),
            "max_abs_target_delta_rad": float(joint_max.max()),
        },
        "output_continuity": {
            "raw_action": continuity(
                raw_jump_abs_sum,
                raw_jump_sq_sum,
                raw_jump_max,
                label="raw_action",
            ),
            "scaled_body_target_rad": continuity(
                target_jump_abs_sum,
                target_jump_sq_sum,
                target_jump_max,
                label="scaled_body_target_rad",
            ),
            "source_a_target_rad": continuity(
                source_jump_abs_sum,
                source_jump_sq_sum,
                source_jump_max,
                label="source_a_target_rad",
            ),
        },
        "phase_metrics": phase_metrics,
        "phase_exemplars": exemplars,
        "candidate_consumed_by_physics": False,
        "actuation_enabled": False,
    }


def run_causal_hold_audit(
    *,
    s3_episode: Path,
    sonic_root: Path,
    source_a_root: Path,
    output_path: Path | None = None,
    observed_at: str | None = None,
    audit_only: bool = False,
    max_samples: int | None = None,
) -> dict[str, Any]:
    s3_episode = s3_episode.resolve()
    sonic_root = sonic_root.resolve()
    source_a_root = source_a_root.resolve()
    output_path = output_path or sonic_root / "SONIC_CAUSAL_HOLD_SHADOW.json"
    inputs, input_bindings = load_mapping_inputs(
        s3_episode=s3_episode, source_a_root=source_a_root
    )
    official = inspect_official_paused_semantics(sonic_root)
    prefix_proof = verify_prefix_equivalence(inputs)
    references = inspect_bundled_references(sonic_root)
    encoder_rows, decoder_rows = _mapping_rows()
    exact_50hz = bool(
        inputs.sample_count > 1
        and all(
            math.isclose(
                float(inputs.times_s[index] - inputs.times_s[index - 1]),
                CONTROL_DT_S,
                rel_tol=0,
                abs_tol=1e-9,
            )
            for index in range(1, inputs.sample_count)
        )
    )
    causal_mapping_ready = bool(
        official["all_markers_match"]
        and prefix_proof["all_equal"]
        and exact_50hz
        and inputs.sample_count >= HISTORY_FRAMES
        and all(row["status"].startswith("available_") for row in encoder_rows)
        and all(row["status"].startswith("available_") for row in decoder_rows)
    )
    encoder_path = sonic_root / "weights/sonic_v1_1/model_encoder.onnx"
    decoder_path = sonic_root / "weights/sonic_v1_1/model_decoder.onnx"
    model_files_ready = encoder_path.is_file() and decoder_path.is_file()
    blockers = []
    if not causal_mapping_ready:
        blockers.append("causal_hold_mapping_not_ready")
    if not model_files_ready:
        blockers.append("encoder_or_decoder_model_missing")
    if audit_only:
        shadow: dict[str, Any] = {
            "status": "audit_only_not_executed",
            "model_forwards": 0,
            "physics_steps": 0,
            "candidate_consumed_by_physics": False,
            "actuation_enabled": False,
        }
    elif blockers:
        shadow = SonicShadowBridge.unavailable_record(
            phase="causal_hold_mapping", sim_time_s=0.0, blockers=blockers
        )
        shadow.update({"model_forwards": 0, "physics_steps": 0})
    else:
        shadow = run_causal_shadow(
            inputs=inputs,
            encoder_path=encoder_path,
            decoder_path=decoder_path,
            max_samples=max_samples,
        )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "implementation": _file_binding(Path(__file__)),
        "inputs": {
            "s3_episode": str(s3_episode),
            "sonic_root": str(sonic_root),
            "source_a_root": str(source_a_root),
            "bindings": input_bindings,
            "encoder_model": _file_binding(encoder_path),
            "decoder_model": _file_binding(decoder_path),
        },
        "official_paused_semantics": official,
        "causality_proof": prefix_proof,
        "bundled_reference_inventory": references,
        "reference_contract": {
            "semantics": REFERENCE_SEMANTICS,
            "available_at": "same control tick",
            "joint_position_source": "privileged_state.ctrl selected by named Source-A body actuators",
            "joint_position_window": "current command repeated for all ten reference frames",
            "joint_velocity_window": "zero for all ten reference frames",
            "root_orientation_source": "same-tick policy_state.base_quaternion_wxyz",
            "root_orientation_window": "current root held for all ten reference frames",
            "depends_on_source_a": True,
            "independent_task_reference": False,
            "maximum_future_row_offset": 0,
        },
        "temporal_contract": {
            "sample_count": inputs.sample_count,
            "first_sim_time_s": float(inputs.times_s[0]),
            "last_sim_time_s": float(inputs.times_s[-1]),
            "sample_period_s": CONTROL_DT_S,
            "exact_50hz": exact_50hz,
            "history_frames": HISTORY_FRAMES,
            "history_order": "oldest_to_newest_with_official_leading_zero_padding",
            "reference_frame_count": G1_FUTURE_FRAMES,
            "reference_step_ticks_field": G1_FUTURE_STEP,
            "effective_future_lookahead_ticks": 0,
            "effective_future_lookahead_s": 0.0,
            "available_causal_sample_count": inputs.sample_count,
        },
        "joint_contract": {
            "body_joint_order_mujoco": list(SONIC_BODY_JOINT_ORDER),
            "source_state_indices": [
                inputs.source_model_joint_order.index(name)
                for name in SONIC_BODY_JOINT_ORDER
            ],
            "source_target_indices": [
                inputs.source_actuator_order.index(name)
                for name in SONIC_BODY_JOINT_ORDER
            ],
            "mujoco_to_isaaclab": list(MUJOCO_TO_ISAACLAB),
            "default_angles_rad": list(DEFAULT_ANGLES),
        },
        "mapping": {
            "selected_encoder_mode": {"name": "g1", "mode_id": 0},
            "encoder_blocks": encoder_rows,
            "decoder_blocks": decoder_rows,
            "inactive_encoder_zero_policy": (
                "official mode filtering, not guessed missing observations"
            ),
        },
        "causal_cpu_shadow": shadow,
        "gates": {
            "source_a_stream_integrity": True,
            "temporal_alignment_ready": exact_50hz,
            "official_paused_semantics_verified": official["all_markers_match"],
            "future_data_independence_verified": prefix_proof["all_equal"],
            "causal_reference_seam_ready": causal_mapping_ready,
            "autoregressive_last_action_ready": causal_mapping_ready,
            "cpu_causal_shadow_executed": shadow.get("status")
            == "executed_non_actuating",
            "independent_reference_generator_ready": False,
            "current_tick_runtime_integration_ready": False,
            "causal_online_controller_ready": False,
            "actuation_enabled": False,
            "candidate_consumed_by_physics": False,
            "official_native_runtime_ready": False,
            "grasp_ab_ready": False,
            "production_accepted": False,
            "learning_validated": False,
            "long_run_authorized": False,
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "model_forwards": int(shadow.get("model_forwards", 0)),
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
        },
        "claim_boundary": (
            "This proves that a same-tick Source-A body command can feed SONIC's "
            "official g1 paused-hold observation shape and that the complete frozen "
            "S3 stream can execute on CPU without future rows or actuation. It remains "
            "a Source-A-dependent offline tracking shadow, not an independent reference "
            "generator, live runtime, hard real-time guarantee, native TensorRT result, "
            "physics-stability result, grasp result, task-success result, or production "
            "admission. Source A remains the only controller that produced S3 physics."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_path, report)
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-episode", type=Path, default=DEFAULT_S3_EPISODE)
    parser.add_argument("--sonic-root", type=Path, default=DEFAULT_SONIC_RUN)
    parser.add_argument("--source-a-root", type=Path, default=DEFAULT_SOURCE_A)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--observed-at")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--max-samples", type=int)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_causal_hold_audit(
        s3_episode=args.s3_episode,
        sonic_root=args.sonic_root,
        source_a_root=args.source_a_root,
        output_path=args.output,
        observed_at=args.observed_at,
        audit_only=args.audit_only,
        max_samples=args.max_samples,
    )
    print(
        json.dumps(
            {
                "output": str(
                    args.output or args.sonic_root / "SONIC_CAUSAL_HOLD_SHADOW.json"
                ),
                "gates": report["gates"],
                "model_forwards": report["audit_scope"]["model_forwards"],
                "physics_steps": report["audit_scope"]["physics_steps"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
