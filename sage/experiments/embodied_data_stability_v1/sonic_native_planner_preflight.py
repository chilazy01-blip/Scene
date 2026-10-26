"""Zero-physics preflight for the official SONIC kinematic planner.

The official deployment currently runs the planner through TensorRT.  The
released artifact is ONNX, however, and the repository retains an ONNX Runtime
backend specifically for CPU development/debugging.  This module mirrors the
active TensorRT input contract while using ONNX Runtime only for deterministic
offline inference.  It never imports MuJoCo and has no actuator write path.
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
from typing import Any, Mapping, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_semantic_shadow import DEFAULT_ANGLES


SCHEMA = "sonic-native-planner-preflight/v1"
PLANNER_FPS = 30.0
CONTROL_FPS = 50.0
DEFAULT_HEIGHT_M = 0.788740
DEFAULT_RANDOM_SEED = 1234
MOTION_LOOKAHEAD_TICKS = 2
EXPECTED_PLANNER_SHA256 = (
    "39b553e197f62f077975ba38512bc04781a3fc37c2af7c6756e04629f760edea"
)
EXPECTED_CONFIG_SHA256 = (
    "326dcc509ad93509cf262871256a74f508f43a8430f61ec6abe8034e985ce948"
)
EXPECTED_ENCODER_SHA256 = (
    "fb97de22819b2057b41459802128d91723d91a25f0ad73e7bfc41a9cf8365bae"
)
EXPECTED_DECODER_SHA256 = (
    "34bae8570d4a4421a5391a5c2befd745d4a02d182ec539e5f9da44c091c67509"
)
EXPECTED_OBSERVATION_CONFIG_SHA256 = (
    "4a67713b310932e50aca81f19188c8d76013148e98b15c8b5bbea995f12e59f0"
)

# This is the value assigned by the active TensorRT deployment implementation.
# Its adjacent comment incorrectly says that indices 0..5 are enabled.  The
# dormant ONNX backend does enable 0..5, so the discrepancy is reported.
ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK = (0, 0, 0, 1, 1, 1, 0, 0, 0, 0, 0)
DORMANT_ONNX_ALLOWED_TOKEN_MASK = (1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0)
ALLOWED_FRAME_COUNTS = (36, 40, 44)

DEFAULT_RUN_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_native_full_20261019_v1"
)
DEFAULT_BUNDLE = DEFAULT_RUN_ROOT / "official_bundle"
DEFAULT_SOURCE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_readmission_20261018_v1/source"
)
DEFAULT_OUTPUT = DEFAULT_RUN_ROOT / "SONIC_NATIVE_PLANNER_PREFLIGHT.json"


def _file_binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _array_sha256(value: Any) -> str:
    import numpy as np

    array = np.ascontiguousarray(value)
    digest = hashlib.sha256()
    digest.update(str(array.dtype).encode("ascii"))
    digest.update(json.dumps(list(array.shape)).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def initialize_context(
    joint_positions_mujoco_rad: Sequence[float] = DEFAULT_ANGLES,
    *,
    height_m: float = DEFAULT_HEIGHT_M,
) -> Any:
    """Mirror ``LocalMotionPlannerBase::InitializeContext`` exactly."""

    import numpy as np

    joints = np.asarray(joint_positions_mujoco_rad, dtype=np.float32)
    if joints.shape != (29,) or not np.isfinite(joints).all():
        raise ValueError("initial joints must be a finite MuJoCo-order [29] vector")
    if not math.isfinite(height_m) or height_m <= 0.0:
        raise ValueError("initial height must be finite and positive")
    frame = np.zeros(36, dtype=np.float32)
    frame[2] = np.float32(height_m)
    frame[3] = 1.0
    frame[7:] = joints
    return np.repeat(frame[None, None, :], 4, axis=1)


def build_planner_inputs(
    context_mujoco_qpos: Any,
    *,
    mode: int,
    target_velocity_m_s: float = -1.0,
    target_height_m: float = -1.0,
    movement_direction: Sequence[float] = (0.0, 0.0, 0.0),
    facing_direction: Sequence[float] = (1.0, 0.0, 0.0),
    random_seed: int = DEFAULT_RANDOM_SEED,
    allowed_token_mask: Sequence[int] = ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK,
) -> dict[str, Any]:
    """Build all eleven version-1 planner tensors with strict dtypes/shapes."""

    import numpy as np

    context = np.asarray(context_mujoco_qpos, dtype=np.float32)
    movement = np.asarray(movement_direction, dtype=np.float32)
    facing = np.asarray(facing_direction, dtype=np.float32)
    mask = np.asarray(allowed_token_mask, dtype=np.int64)
    if context.shape != (1, 4, 36) or not np.isfinite(context).all():
        raise ValueError("planner context must be finite float32 [1,4,36]")
    if movement.shape != (3,) or not np.isfinite(movement).all():
        raise ValueError("movement direction must be a finite [3] vector")
    if facing.shape != (3,) or not np.isfinite(facing).all():
        raise ValueError("facing direction must be a finite [3] vector")
    if float(np.linalg.norm(facing)) <= 0.0:
        raise ValueError("facing direction must be nonzero")
    if mask.shape != (11,) or not np.isin(mask, (0, 1)).all() or not mask.any():
        raise ValueError("allowed token mask must be a nonempty binary [11] vector")
    if mode < 0 or mode >= 20:
        raise ValueError("version-1 planner mode must be in [0,20)")
    if not math.isfinite(target_velocity_m_s) or not math.isfinite(target_height_m):
        raise ValueError("planner scalar commands must be finite")
    return {
        "context_mujoco_qpos": context,
        "target_vel": np.asarray([target_velocity_m_s], dtype=np.float32),
        "mode": np.asarray([mode], dtype=np.int64),
        "movement_direction": movement[None, :],
        "facing_direction": facing[None, :],
        "random_seed": np.asarray([random_seed], dtype=np.int64),
        "has_specific_target": np.zeros((1, 1), dtype=np.int64),
        "specific_target_positions": np.zeros((1, 4, 3), dtype=np.float32),
        "specific_target_headings": np.zeros((1, 4), dtype=np.float32),
        "allowed_pred_num_tokens": mask[None, :],
        "height": np.asarray([target_height_m], dtype=np.float32),
    }


def validate_planner_outputs(
    mujoco_qpos: Any,
    num_pred_frames: Any,
    *,
    allowed_frame_counts: Sequence[int] = ALLOWED_FRAME_COUNTS,
) -> tuple[Any, int, dict[str, Any]]:
    """Fail closed on the planner's valid output prefix."""

    import numpy as np

    qpos = np.asarray(mujoco_qpos)
    count_array = np.asarray(num_pred_frames)
    if qpos.shape != (1, 64, 36) or qpos.dtype != np.float32:
        raise ValueError(
            f"planner qpos must be float32 [1,64,36], got {qpos.dtype} {qpos.shape}"
        )
    if count_array.size != 1 or not np.issubdtype(count_array.dtype, np.integer):
        raise ValueError("num_pred_frames must contain one integer")
    count = int(count_array.reshape(-1)[0])
    if count not in tuple(int(value) for value in allowed_frame_counts):
        raise ValueError(
            f"planner returned {count} frames outside deployment mask result set "
            f"{tuple(allowed_frame_counts)}"
        )
    valid = np.ascontiguousarray(qpos[0, :count])
    if not np.isfinite(valid).all():
        raise ValueError("planner valid output contains nonfinite values")
    quaternion_norms = np.linalg.norm(valid[:, 3:7].astype(np.float64), axis=1)
    maximum_norm_error = float(np.max(np.abs(quaternion_norms - 1.0)))
    if maximum_norm_error > 1e-3:
        raise ValueError(
            f"planner output quaternion norm error {maximum_norm_error} exceeds 1e-3"
        )
    return (
        valid,
        count,
        {
            "valid_frame_count_30hz": count,
            "valid_duration_s": count / PLANNER_FPS,
            "maximum_quaternion_norm_error": maximum_norm_error,
            "valid_qpos_sha256": _array_sha256(valid),
        },
    )


def _quaternion_slerp(q0: Any, q1: Any, fraction: float) -> Any:
    import numpy as np

    left = np.asarray(q0, dtype=np.float64)
    right = np.asarray(q1, dtype=np.float64)
    left /= np.linalg.norm(left)
    right /= np.linalg.norm(right)
    dot = float(np.dot(left, right))
    if dot < 0.0:
        right = -right
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        result = left + fraction * (right - left)
        return result / np.linalg.norm(result)
    angle = math.acos(dot)
    denominator = math.sin(angle)
    return (
        math.sin((1.0 - fraction) * angle) / denominator * left
        + math.sin(fraction * angle) / denominator * right
    )


def resample_qpos_50hz(valid_qpos_30hz: Any) -> Any:
    """Mirror official 30 Hz to 50 Hz root/joint interpolation."""

    import numpy as np

    source = np.asarray(valid_qpos_30hz, dtype=np.float32)
    if source.ndim != 2 or source.shape[1] != 36 or source.shape[0] < 2:
        raise ValueError("resampling requires at least two [36] qpos frames")
    if not np.isfinite(source).all():
        raise ValueError("resampling source must be finite")
    output_count = int(math.floor(source.shape[0] / PLANNER_FPS * CONTROL_FPS))
    output = np.empty((output_count, 36), dtype=np.float64)
    for output_frame in range(output_count):
        source_frame = output_frame / CONTROL_FPS * PLANNER_FPS
        lower = int(math.floor(source_frame))
        upper = min(lower + 1, source.shape[0] - 1)
        fraction = source_frame - lower
        output[output_frame, :3] = (1.0 - fraction) * source[
            lower, :3
        ] + fraction * source[upper, :3]
        output[output_frame, 3:7] = _quaternion_slerp(
            source[lower, 3:7], source[upper, 3:7], fraction
        )
        output[output_frame, 7:] = (1.0 - fraction) * source[
            lower, 7:
        ] + fraction * source[upper, 7:]
    return output


def context_from_motion_50hz(
    qpos_50hz: Any,
    *,
    generation_frame: int = MOTION_LOOKAHEAD_TICKS,
) -> Any:
    """Mirror ``UpdateContextFromMotion`` without its cancelling order swaps."""

    import numpy as np

    motion = np.asarray(qpos_50hz, dtype=np.float64)
    if motion.ndim != 2 or motion.shape[1] != 36 or motion.shape[0] < 2:
        raise ValueError("context source must contain at least two [36] frames")
    if generation_frame < 0 or not np.isfinite(motion).all():
        raise ValueError("context source and generation frame must be valid")
    context = np.empty((1, 4, 36), dtype=np.float32)
    generation_time = generation_frame / CONTROL_FPS
    for index in range(4):
        sample_50hz = (generation_time + index / PLANNER_FPS) * CONTROL_FPS
        lower = min(int(math.floor(sample_50hz)), motion.shape[0] - 1)
        upper = min(lower + 1, motion.shape[0] - 1)
        fraction = sample_50hz - lower
        row = context[0, index]
        row[:3] = (1.0 - fraction) * motion[lower, :3] + fraction * motion[upper, :3]
        row[3:7] = _quaternion_slerp(motion[lower, 3:7], motion[upper, 3:7], fraction)
        row[7:] = (1.0 - fraction) * motion[lower, 7:] + fraction * motion[upper, 7:]
    return context


def _contract_audit(source_root: Path) -> dict[str, Any]:
    base = source_root / "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref"
    planner_base = base / "include/localmotion_kplanner.hpp"
    active_backend = base / "include/localmotion_kplanner_tensorrt.hpp"
    dormant_backend = base / "include/localmotion_kplanner_onnx.hpp"
    policy_parameters = base / "include/policy_parameters.hpp"
    active_text = active_backend.read_text(encoding="utf-8")
    dormant_text = dormant_backend.read_text(encoding="utf-8")
    markers = {
        "active_backend_first_three_disabled": all(
            f"allowed_pred_num_tokens_[{index}] = 0" in active_text
            for index in range(3)
        ),
        "active_backend_next_three_enabled": all(
            f"allowed_pred_num_tokens_[{index}] = 1" in active_text
            for index in range(3, 6)
        ),
        "dormant_backend_first_six_enabled": all(
            f"allowed_pred_num_tokens_[{index}] = 1" in dormant_text
            for index in range(6)
        ),
        "default_height_matches": "double default_height = 0.788740"
        in planner_base.read_text(encoding="utf-8"),
        "default_seed_matches": "int initial_random_seed = 1234"
        in planner_base.read_text(encoding="utf-8"),
    }
    return {
        "source_files": {
            "planner_base": _file_binding(planner_base),
            "active_tensorrt_backend": _file_binding(active_backend),
            "dormant_onnx_backend": _file_binding(dormant_backend),
            "policy_parameters": _file_binding(policy_parameters),
        },
        "markers": markers,
        "all_required_markers_present": all(markers.values()),
        "active_deployment_allowed_token_mask": list(
            ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK
        ),
        "dormant_onnx_allowed_token_mask": list(DORMANT_ONNX_ALLOWED_TOKEN_MASK),
        "mask_discrepancy_present": ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK
        != DORMANT_ONNX_ALLOWED_TOKEN_MASK,
        "resolution": "CPU inference uses the active TensorRT backend's assigned values",
    }


def _run_once(session: Any, inputs: Mapping[str, Any]) -> tuple[Any, Any, float]:
    started = time.perf_counter()
    qpos, count = session.run(None, dict(inputs))
    return qpos, count, time.perf_counter() - started


def run_preflight(
    *,
    bundle_root: Path = DEFAULT_BUNDLE,
    source_root: Path = DEFAULT_SOURCE,
) -> dict[str, Any]:
    """Run official initialization plus one forward-walk replan on CPU."""

    import numpy as np
    import onnxruntime as ort

    bundle_root = bundle_root.resolve()
    planner_path = bundle_root / "planner/target_vel/V2/planner_sonic.onnx"
    config_path = bundle_root / "config.json"
    encoder_path = bundle_root / "policy/sonic_v1_1/model_encoder.onnx"
    decoder_path = bundle_root / "policy/sonic_v1_1/model_decoder.onnx"
    observation_path = bundle_root / "policy/sonic_v1_1/observation_config.yaml"
    bindings = {
        "release_config": _file_binding(config_path),
        "planner": _file_binding(planner_path),
        "encoder": _file_binding(encoder_path),
        "decoder": _file_binding(decoder_path),
        "observation_config": _file_binding(observation_path),
    }
    expected_hashes = {
        "release_config": EXPECTED_CONFIG_SHA256,
        "planner": EXPECTED_PLANNER_SHA256,
        "encoder": EXPECTED_ENCODER_SHA256,
        "decoder": EXPECTED_DECODER_SHA256,
        "observation_config": EXPECTED_OBSERVATION_CONFIG_SHA256,
    }
    mismatches = {
        name: {"expected": expected_hashes[name], "actual": record["sha256"]}
        for name, record in bindings.items()
        if record["sha256"] != expected_hashes[name]
    }
    if mismatches:
        raise RuntimeError(f"official bundle hash mismatch: {mismatches}")
    release_config = json.loads(config_path.read_text(encoding="utf-8"))
    if release_config["shared_files"]["planner"] != "planner_sonic.onnx":
        raise RuntimeError("release config does not declare planner_sonic.onnx")

    source_contract = _contract_audit(source_root)
    if not source_contract["all_required_markers_present"]:
        raise RuntimeError("official source contract markers are incomplete")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    load_started = time.perf_counter()
    session = ort.InferenceSession(
        str(planner_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    load_seconds = time.perf_counter() - load_started
    actual_inputs = {
        node.name: {"shape": list(node.shape), "type": node.type}
        for node in session.get_inputs()
    }
    actual_outputs = {
        node.name: {"shape": list(node.shape), "type": node.type}
        for node in session.get_outputs()
    }
    expected_input_names = {
        "context_mujoco_qpos",
        "target_vel",
        "mode",
        "movement_direction",
        "facing_direction",
        "random_seed",
        "has_specific_target",
        "specific_target_positions",
        "specific_target_headings",
        "allowed_pred_num_tokens",
        "height",
    }
    if set(actual_inputs) != expected_input_names:
        raise RuntimeError(f"planner input interface mismatch: {sorted(actual_inputs)}")
    if set(actual_outputs) != {"mujoco_qpos", "num_pred_frames"}:
        raise RuntimeError(
            f"planner output interface mismatch: {sorted(actual_outputs)}"
        )

    initial_context = initialize_context()
    idle_inputs = build_planner_inputs(initial_context, mode=0)
    idle_first_raw, idle_count_raw, idle_first_seconds = _run_once(session, idle_inputs)
    idle_second_raw, idle_second_count_raw, idle_second_seconds = _run_once(
        session, idle_inputs
    )
    idle_first, _, idle_metrics = validate_planner_outputs(
        idle_first_raw, idle_count_raw
    )
    idle_second, _, _ = validate_planner_outputs(idle_second_raw, idle_second_count_raw)
    idle_deterministic = bool(
        np.array_equal(idle_first, idle_second)
        and np.array_equal(idle_count_raw, idle_second_count_raw)
    )
    idle_50hz = resample_qpos_50hz(idle_first)
    walk_context = context_from_motion_50hz(idle_50hz)

    walk_inputs = build_planner_inputs(
        walk_context,
        mode=2,
        target_velocity_m_s=-1.0,
        movement_direction=(1.0, 0.0, 0.0),
        facing_direction=(1.0, 0.0, 0.0),
    )
    walk_first_raw, walk_count_raw, walk_first_seconds = _run_once(session, walk_inputs)
    walk_second_raw, walk_second_count_raw, walk_second_seconds = _run_once(
        session, walk_inputs
    )
    walk_first, _, walk_metrics = validate_planner_outputs(
        walk_first_raw, walk_count_raw
    )
    walk_second, _, _ = validate_planner_outputs(walk_second_raw, walk_second_count_raw)
    walk_deterministic = bool(
        np.array_equal(walk_first, walk_second)
        and np.array_equal(walk_count_raw, walk_second_count_raw)
    )
    walk_50hz = resample_qpos_50hz(walk_first)
    root_delta = walk_50hz[-1, :3] - walk_50hz[0, :3]
    horizontal_path = float(
        np.linalg.norm(np.diff(walk_50hz[:, :2], axis=0), axis=1).sum()
    )
    horizontal_net = float(np.linalg.norm(root_delta[:2]))
    context_to_walk_joint_delta = float(
        np.max(np.abs(walk_first[0, 7:] - walk_context[0, -1, 7:]))
    )
    context_to_walk_root_delta = float(
        np.linalg.norm(walk_first[0, :3] - walk_context[0, -1, :3])
    )
    walk_motion_present = bool(horizontal_net >= 0.05 and root_delta[0] > 0.0)
    zero_physics_admitted = bool(
        idle_deterministic
        and walk_deterministic
        and walk_motion_present
        and idle_metrics["maximum_quaternion_norm_error"] <= 1e-3
        and walk_metrics["maximum_quaternion_norm_error"] <= 1e-3
    )

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "passed" if zero_physics_admitted else "not_admitted",
        "purpose": "official SONIC planner zero-physics initialization and forward-walk preflight",
        "official_bundle": bindings,
        "official_source_contract": source_contract,
        "runtime": {
            "python": platform.python_version(),
            "onnxruntime": ort.__version__,
            "providers": session.get_providers(),
            "session_load_seconds": load_seconds,
            "maximum_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "input_interface": actual_inputs,
            "output_interface": actual_outputs,
        },
        "initialization": {
            "joint_order": "MuJoCo",
            "height_m": DEFAULT_HEIGHT_M,
            "random_seed": DEFAULT_RANDOM_SEED,
            "context_sha256": _array_sha256(initial_context),
            "command": {
                "mode": 0,
                "target_velocity_m_s": -1.0,
                "movement_direction": [0.0, 0.0, 0.0],
                "facing_direction": [1.0, 0.0, 0.0],
            },
            "allowed_token_mask": list(ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK),
            "inference_seconds": [idle_first_seconds, idle_second_seconds],
            "exact_repeat_deterministic": idle_deterministic,
            "output": idle_metrics,
            "resampled_frame_count_50hz": int(idle_50hz.shape[0]),
            "resampled_qpos_sha256": _array_sha256(idle_50hz),
        },
        "forward_walk_replan": {
            "context_source": "official idle output at generation frame +2 ticks",
            "context_sha256": _array_sha256(walk_context),
            "command": {
                "mode": 2,
                "target_velocity_m_s": -1.0,
                "movement_direction": [1.0, 0.0, 0.0],
                "facing_direction": [1.0, 0.0, 0.0],
            },
            "allowed_token_mask": list(ACTIVE_DEPLOYMENT_ALLOWED_TOKEN_MASK),
            "inference_seconds": [walk_first_seconds, walk_second_seconds],
            "exact_repeat_deterministic": walk_deterministic,
            "output": walk_metrics,
            "resampled_frame_count_50hz": int(walk_50hz.shape[0]),
            "resampled_qpos_sha256": _array_sha256(walk_50hz),
            "root_displacement_xyz_m": root_delta.tolist(),
            "horizontal_net_displacement_m": horizontal_net,
            "horizontal_path_length_m": horizontal_path,
            "context_to_first_prediction_root_delta_m": context_to_walk_root_delta,
            "context_to_first_prediction_max_joint_delta_rad": context_to_walk_joint_delta,
            "forward_motion_threshold_m": 0.05,
            "forward_motion_present": walk_motion_present,
        },
        "execution_limits": {
            "physics_executed": False,
            "physics_steps": 0,
            "actuator_writes": 0,
            "model_forward_calls": 4,
            "network_access_during_preflight": False,
            "training_executed": False,
            "rendering_executed": False,
        },
        "gates": {
            "official_full_bundle_hash_bound": not mismatches,
            "active_deployment_contract_mirrored": source_contract[
                "all_required_markers_present"
            ],
            "idle_planner_output_ready": idle_deterministic,
            "forward_walk_planner_output_ready": walk_deterministic
            and walk_motion_present,
            "planner_zero_physics_admitted": zero_physics_admitted,
            "sonic_policy_reference_integration_ready": zero_physics_admitted,
            "physics_smoke_authorized": False,
            "task_success_validated": False,
            "grasp_success_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
        "next_step": (
            "Feed the hash-bound planner trajectory into the official SONIC v1.1 "
            "encoder/decoder observation path in a zero-physics closed-loop shadow; "
            "do not start physics yet."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-root", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    report = run_preflight(
        bundle_root=arguments.bundle_root,
        source_root=arguments.source_root,
    )
    write_json_atomic(arguments.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["gates"]["planner_zero_physics_admitted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
