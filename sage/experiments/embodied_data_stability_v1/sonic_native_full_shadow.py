"""End-to-end zero-physics shadow for planner-driven official SONIC v1.1.

The kinematic planner supplies the future body reference.  The SONIC encoder
and decoder consume that reference plus a kinematic oracle state derived from
the same trajectory.  The oracle is intentionally not a dynamics claim: this
stage proves the complete model/data seam without MuJoCo or actuator writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import resource
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_native_planner_preflight import (
    DEFAULT_BUNDLE,
    DEFAULT_OUTPUT as DEFAULT_PREFLIGHT_OUTPUT,
    DEFAULT_RUN_ROOT,
    EXPECTED_DECODER_SHA256,
    EXPECTED_ENCODER_SHA256,
    EXPECTED_OBSERVATION_CONFIG_SHA256,
    EXPECTED_PLANNER_SHA256,
    _array_sha256,
    _file_binding,
    _run_once,
    build_planner_inputs,
    context_from_motion_50hz,
    initialize_context,
    resample_qpos_50hz,
    validate_planner_outputs,
)
from .sonic_offline_observation_mapper import (
    G1_LOOKAHEAD_TICKS,
    MappingInputs,
    build_decoder_blocks,
    build_g1_encoder_blocks,
    prepare_decoder_state,
)
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
    parse_v11_config_order,
)


SCHEMA = "sonic-native-full-zero-physics-shadow/v1"
CONTROL_DT_S = 0.02
DEFAULT_OUTPUT = DEFAULT_RUN_ROOT / "SONIC_NATIVE_FULL_ZERO_PHYSICS_SHADOW.json"


def _quat_conjugate(quaternion: Any) -> Any:
    import numpy as np

    value = np.asarray(quaternion, dtype=np.float64)
    return np.asarray([value[0], -value[1], -value[2], -value[3]])


def _quat_multiply(left: Any, right: Any) -> Any:
    import numpy as np

    w1, x1, y1, z1 = np.asarray(left, dtype=np.float64)
    w2, x2, y2, z2 = np.asarray(right, dtype=np.float64)
    return np.asarray(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float64,
    )


def _body_angular_velocity(quaternions_wxyz: Any) -> Any:
    """Finite-difference body-frame gyro values for a 50 Hz qpos stream."""

    import numpy as np

    quaternions = np.asarray(quaternions_wxyz, dtype=np.float64)
    if quaternions.ndim != 2 or quaternions.shape[1] != 4:
        raise ValueError("quaternion stream must be [N,4]")
    norms = np.linalg.norm(quaternions, axis=1)
    if not np.isfinite(quaternions).all() or np.max(np.abs(norms - 1.0)) > 1e-3:
        raise ValueError("quaternion stream must be finite and unit length")
    result = np.zeros((quaternions.shape[0], 3), dtype=np.float64)
    for index in range(quaternions.shape[0] - 1):
        delta = _quat_multiply(
            _quat_conjugate(quaternions[index]), quaternions[index + 1]
        )
        if delta[0] < 0.0:
            delta = -delta
        vector_norm = float(np.linalg.norm(delta[1:]))
        if vector_norm > 1e-12:
            angle = 2.0 * math.atan2(vector_norm, float(delta[0]))
            result[index] = delta[1:] / vector_norm * angle / CONTROL_DT_S
    if result.shape[0] > 1:
        result[-1] = result[-2]
    return result


def mapping_inputs_from_planner_qpos(qpos_50hz: Any) -> MappingInputs:
    """Create policy-visible kinematic state without consulting Source A."""

    import numpy as np

    qpos = np.asarray(qpos_50hz, dtype=np.float64)
    if qpos.ndim != 2 or qpos.shape[1] != 36:
        raise ValueError("planner qpos stream must be [N,36]")
    if qpos.shape[0] <= G1_LOOKAHEAD_TICKS or not np.isfinite(qpos).all():
        raise ValueError("planner qpos stream lacks a complete future window")
    quaternion_norms = np.linalg.norm(qpos[:, 3:7], axis=1)
    if np.max(np.abs(quaternion_norms - 1.0)) > 1e-3:
        raise ValueError("planner qpos stream contains invalid quaternions")
    positions = qpos[:, 7:].copy()
    velocities = np.empty_like(positions)
    velocities[:-1] = np.diff(positions, axis=0) / CONTROL_DT_S
    velocities[-1] = velocities[-2]
    return MappingInputs(
        times_s=np.arange(qpos.shape[0], dtype=np.float64) * CONTROL_DT_S,
        body_position_mujoco_rad=positions,
        body_velocity_mujoco_rad_s=velocities,
        base_quaternion_wxyz=qpos[:, 3:7].copy(),
        base_angular_velocity_rad_s=_body_angular_velocity(qpos[:, 3:7]),
        source_targets_mujoco_rad=positions.copy(),
        phase_events=({"sim_time_s": 0.0, "phase": "official_planner_walk"},),
        source_model_joint_order=(),
        source_actuator_order=(),
    )


def _make_session(model_path: Path) -> Any:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def run_policy_sequence(
    *,
    inputs: MappingInputs,
    encoder: Any,
    decoder: Any,
) -> dict[str, Any]:
    """Run all ticks with a complete 0.9 s official g1 future window."""

    import numpy as np

    count = inputs.sample_count - G1_LOOKAHEAD_TICKS
    if count <= 0:
        raise ValueError("policy sequence has no complete reference window")
    raw_actions = np.zeros((count, 29), dtype=np.float32)
    targets = np.zeros((count, 29), dtype=np.float64)
    input_hashes = {
        "encoder": hashlib.sha256(),
        "decoder": hashlib.sha256(),
        "tokens": hashlib.sha256(),
    }
    prepared = prepare_decoder_state(inputs)
    inference_seconds = []
    for index in range(count):
        encoder_values = ENCODER_ASSEMBLER.assemble(
            build_g1_encoder_blocks(inputs, index)
        )
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        started = time.perf_counter()
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_values = DECODER_ASSEMBLER.assemble(
            build_decoder_blocks(
                inputs,
                index,
                token_state=token,
                logged_last_actions_isaaclab=raw_actions,
                prepared_state=prepared,
            )
        )
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        action = decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[0]
        inference_seconds.append(time.perf_counter() - started)
        action = np.asarray(action, dtype=np.float32).reshape(-1)
        if action.shape != (29,) or not np.isfinite(action).all():
            raise RuntimeError("SONIC decoder returned an invalid action")
        raw_actions[index] = action
        targets[index] = body_joint_target_from_raw_action(
            action,
            phase="official_planner_walk",
            sim_time_s=float(inputs.times_s[index]),
        ).position_target_rad
        input_hashes["encoder"].update(encoder_input.tobytes())
        input_hashes["decoder"].update(decoder_input.tobytes())
        input_hashes["tokens"].update(np.asarray(token, dtype=np.float32).tobytes())
    if not np.isfinite(targets).all():
        raise RuntimeError("scaled SONIC targets contain nonfinite values")
    reference = np.asarray(inputs.body_position_mujoco_rad[:count])
    previous = np.vstack([reference[0], targets[:-1]])
    return {
        "tick_count": count,
        "raw_actions": raw_actions,
        "targets_mujoco_rad": targets,
        "encoder_input_sha256": input_hashes["encoder"].hexdigest(),
        "encoder_tokens_sha256": input_hashes["tokens"].hexdigest(),
        "decoder_input_sha256": input_hashes["decoder"].hexdigest(),
        "raw_actions_sha256": _array_sha256(raw_actions),
        "targets_sha256": _array_sha256(targets),
        "maximum_target_step_rad": float(np.max(np.abs(targets - previous))),
        "maximum_target_to_kinematic_state_delta_rad": float(
            np.max(np.abs(targets - reference))
        ),
        "mean_encoder_decoder_seconds": float(np.mean(inference_seconds)),
        "maximum_encoder_decoder_seconds": float(np.max(inference_seconds)),
    }


def run_full_shadow(
    *,
    bundle_root: Path = DEFAULT_BUNDLE,
    preflight_path: Path = DEFAULT_PREFLIGHT_OUTPUT,
) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as ort

    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if not preflight["gates"]["planner_zero_physics_admitted"]:
        raise RuntimeError("planner preflight is not admitted")
    if (
        canonical_sha256(
            {
                key: value
                for key, value in preflight.items()
                if key != "content_sha256_excluding_this_field"
            }
        )
        != preflight["content_sha256_excluding_this_field"]
    ):
        raise RuntimeError("planner preflight internal content hash mismatch")

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
    idle_raw, idle_count, _ = _run_once(
        planner, build_planner_inputs(initialize_context(), mode=0)
    )
    idle, _, _ = validate_planner_outputs(idle_raw, idle_count)
    idle_50hz = resample_qpos_50hz(idle)
    walk_context = context_from_motion_50hz(idle_50hz)
    walk_raw, walk_count, _ = _run_once(
        planner,
        build_planner_inputs(
            walk_context,
            mode=2,
            movement_direction=(1.0, 0.0, 0.0),
            facing_direction=(1.0, 0.0, 0.0),
        ),
    )
    walk, _, _ = validate_planner_outputs(walk_raw, walk_count)
    walk_50hz = resample_qpos_50hz(walk)
    del planner

    inputs = mapping_inputs_from_planner_qpos(walk_50hz)
    encoder = _make_session(encoder_path)
    decoder = _make_session(decoder_path)
    first = run_policy_sequence(inputs=inputs, encoder=encoder, decoder=decoder)
    second = run_policy_sequence(inputs=inputs, encoder=encoder, decoder=decoder)
    deterministic = all(
        first[name] == second[name]
        for name in (
            "encoder_input_sha256",
            "encoder_tokens_sha256",
            "decoder_input_sha256",
            "raw_actions_sha256",
            "targets_sha256",
        )
    )
    horizontal_displacement = float(
        np.linalg.norm(walk_50hz[first["tick_count"] - 1, :2] - walk_50hz[0, :2])
    )
    admitted = bool(
        deterministic
        and first["tick_count"] > 0
        and horizontal_displacement >= 0.05
        and np.isfinite(first["targets_mujoco_rad"]).all()
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "passed" if admitted else "not_admitted",
        "purpose": "official planner to SONIC v1.1 encoder/decoder zero-physics seam",
        "inputs": {
            "planner_preflight": _file_binding(preflight_path),
            "planner_model": _file_binding(planner_path),
            "encoder_model": _file_binding(encoder_path),
            "decoder_model": _file_binding(decoder_path),
            "observation_config": _file_binding(observation_path),
            "observation_layout": layout,
        },
        "reference": {
            "source": "official SONIC kinematic planner",
            "source_a_body_reference_used": False,
            "qpos_frame_count_50hz": int(walk_50hz.shape[0]),
            "qpos_sha256": _array_sha256(walk_50hz),
            "complete_policy_window_tick_count": first["tick_count"],
            "policy_window_horizontal_displacement_m": horizontal_displacement,
            "state_model": (
                "kinematic oracle following the planner qpos; no dynamics or tracking "
                "success is implied"
            ),
        },
        "policy_shadow": {
            key: value
            for key, value in first.items()
            if key not in {"raw_actions", "targets_mujoco_rad"}
        },
        "repeat": {
            "exact_hash_deterministic": deterministic,
            "raw_actions_sha256": second["raw_actions_sha256"],
            "targets_sha256": second["targets_sha256"],
        },
        "runtime": {
            "python": platform.python_version(),
            "onnxruntime": ort.__version__,
            "providers": encoder.get_providers(),
            "maximum_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "execution_limits": {
            "physics_executed": False,
            "physics_steps": 0,
            "actuator_writes": 0,
            "planner_forward_calls": 2,
            "encoder_forward_calls": first["tick_count"] * 2,
            "decoder_forward_calls": first["tick_count"] * 2,
            "source_a_body_command_used": False,
            "output_clipping_or_slew_limiting": False,
            "training_executed": False,
            "rendering_executed": False,
        },
        "capability_boundary": {
            "body_controller": "official SONIC v1.1, 29 DoF",
            "body_motion_source": "official SONIC kinematic planner",
            "dex3_hand_controller": "not supplied by SONIC v1.1; remains a separate future seam",
            "task_planning": "not validated",
        },
        "gates": {
            "official_planner_to_policy_seam_ready": admitted,
            "source_a_free_body_route_ready": admitted,
            "zero_physics_full_sonic_body_candidate_ready": admitted,
            "physics_smoke_authorized": False,
            "dynamic_tracking_validated": False,
            "task_success_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
        "next_step": (
            "Build a bounded MuJoCo shadow using the official planner reference and "
            "SONIC body commands only, then apply the existing finite/envelope/contact "
            "guards before requesting any active physics window."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--preflight", type=Path, default=DEFAULT_PREFLIGHT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    report = run_full_shadow(
        bundle_root=arguments.bundle_root,
        preflight_path=arguments.preflight,
    )
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["gates"]["official_planner_to_policy_seam_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
