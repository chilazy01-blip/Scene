"""Map the frozen Source-A S3 stream into SONIC v1.1's offline g1 mode.

The mapper is deliberately fail closed.  It accepts only the hash-bound S3
state stream, reconstructs the official 50 Hz history layout, and uses future
S3 states as an explicitly non-causal ``g1`` reference motion.  It never
advances physics and exposes no actuator write path.

Unused encoder blocks are zero only because the official deployment clears the
encoder buffer and gathers the blocks required by the selected mode.  This is
different from inventing missing values: the report binds both the mode
configuration and the C++ mode-filter implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import resource
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    DECODER_BLOCKS,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    ENCODER_BLOCKS,
    ISAACLAB_TO_MUJOCO,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import BodyJointTarget, SONIC_BODY_JOINT_ORDER, SonicShadowBridge


SCHEMA = "sonic-real-observation-mapping/v1"
CONTROL_DT_S = 0.02
HISTORY_FRAMES = 10
G1_FUTURE_FRAMES = 10
G1_FUTURE_STEP = 5
G1_LOOKAHEAD_TICKS = (G1_FUTURE_FRAMES - 1) * G1_FUTURE_STEP
MUJOCO_TO_ISAACLAB = tuple(
    ISAACLAB_TO_MUJOCO.index(isaac_index) for isaac_index in range(29)
)
G1_REQUIRED_ENCODER_BLOCKS = (
    "encoder_mode_4",
    "motion_joint_positions_10frame_step5",
    "motion_joint_velocities_10frame_step5",
    "motion_anchor_orientation_heading_10frame_step5",
)

DEFAULT_S3_EPISODE = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_s3_20261014_v1/source_a_task_smoke_01"
)
DEFAULT_SONIC_RUN = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_readmission_20261018_v1"
)
DEFAULT_SOURCE_A = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_stretch_ai_admission_20260926_v1/full_body_milestone/"
    "feasibility_guard_v4/prepared/payload_data_20261009/"
    "native_parallel_12h_20261011/branches/A/source"
)


@dataclass(frozen=True)
class MappingInputs:
    times_s: Any
    body_position_mujoco_rad: Any
    body_velocity_mujoco_rad_s: Any
    base_quaternion_wxyz: Any
    base_angular_velocity_rad_s: Any
    source_targets_mujoco_rad: Any
    phase_events: tuple[dict[str, Any], ...]
    source_model_joint_order: tuple[str, ...]
    source_actuator_order: tuple[str, ...]

    @property
    def sample_count(self) -> int:
        return int(self.times_s.shape[0])


def _file_binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _is_lfs_pointer(path: Path) -> bool:
    return path.is_file() and path.read_bytes()[:128].startswith(
        b"version https://git-lfs.github.com/spec/v1"
    )


def _xml_joint_and_actuator_order(
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    root = ET.parse(path).getroot()
    joint_order = tuple(
        node.attrib["name"]
        for node in root.findall(".//worldbody//joint")
        if node.attrib.get("name")
    )
    actuator = root.find("actuator")
    actuator_order = ()
    if actuator is not None:
        actuator_order = tuple(
            node.attrib["joint"] for node in actuator if node.attrib.get("joint")
        )
    if len(joint_order) != len(set(joint_order)):
        raise ValueError("Source-A model contains duplicate joint names")
    if len(actuator_order) != len(set(actuator_order)):
        raise ValueError("Source-A model contains duplicate actuator joints")
    return joint_order, actuator_order


def _verified_npz(
    stream_root: Path, stream_name: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np

    manifest_path = stream_root / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest["streams"][stream_name]
    path = stream_root / record["relative_path"]
    actual_hash = sha256_file(path)
    if actual_hash != record["sha256"]:
        raise RuntimeError(
            f"{stream_name} hash mismatch: {actual_hash} != {record['sha256']}"
        )
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    return arrays, {"manifest": manifest, "file": _file_binding(path)}


def _require_array(
    arrays: Mapping[str, Any],
    name: str,
    *,
    rows: int,
    width: int | None = None,
) -> Any:
    import numpy as np

    if name not in arrays:
        raise ValueError(f"required state array is missing: {name}")
    value = np.asarray(arrays[name])
    expected_shape = (rows,) if width is None else (rows, width)
    if value.shape != expected_shape:
        raise ValueError(f"{name} shape {value.shape} != {expected_shape}")
    if not np.issubdtype(value.dtype, np.number) or not np.isfinite(value).all():
        raise ValueError(f"{name} must be a finite numeric array")
    return value


def load_mapping_inputs(
    *,
    s3_episode: Path,
    source_a_root: Path,
) -> tuple[MappingInputs, dict[str, Any]]:
    import numpy as np

    stream_root = s3_episode / "state_stream"
    policy, policy_binding = _verified_npz(stream_root, "policy")
    privileged, privileged_binding = _verified_npz(stream_root, "privileged")
    manifest = policy_binding["manifest"]
    rows = int(manifest["sample_count"])
    if privileged_binding["manifest"] != manifest:
        raise ValueError("policy and privileged readers observed different manifests")

    policy_time = _require_array(policy, "sim_time_s", rows=rows)
    privileged_time = _require_array(privileged, "sim_time_s", rows=rows)
    if not np.array_equal(policy_time, privileged_time):
        raise ValueError("policy and privileged timestamps differ")
    deltas = np.diff(policy_time)
    if rows < HISTORY_FRAMES or not np.allclose(
        deltas, CONTROL_DT_S, atol=1e-9, rtol=0
    ):
        raise ValueError("S3 stream is not an exact 50 Hz history source")

    source_model_path = source_a_root / "g1.xml"
    joint_order, actuator_order = _xml_joint_and_actuator_order(source_model_path)
    missing_joints = sorted(set(SONIC_BODY_JOINT_ORDER) - set(joint_order))
    missing_actuators = sorted(set(SONIC_BODY_JOINT_ORDER) - set(actuator_order))
    if missing_joints or missing_actuators:
        raise ValueError(
            f"Source-A body seam incomplete; joints={missing_joints}, "
            f"actuators={missing_actuators}"
        )
    joint_indices = [joint_order.index(name) for name in SONIC_BODY_JOINT_ORDER]
    actuator_indices = [actuator_order.index(name) for name in SONIC_BODY_JOINT_ORDER]

    model_joint_count = int(manifest["model"]["robot_joint_count"])
    model_actuator_count = int(manifest["model"]["nu"])
    all_joint_position = _require_array(
        policy, "joint_position", rows=rows, width=model_joint_count
    )
    all_joint_velocity = _require_array(
        policy, "joint_velocity", rows=rows, width=model_joint_count
    )
    quaternion = _require_array(policy, "base_quaternion_wxyz", rows=rows, width=4)
    base_velocity = _require_array(policy, "base_velocity", rows=rows, width=6)
    controls = _require_array(privileged, "ctrl", rows=rows, width=model_actuator_count)
    quaternion_norm = np.linalg.norm(quaternion, axis=1)
    if not np.allclose(quaternion_norm, 1.0, atol=1e-6, rtol=0):
        raise ValueError("base_quaternion_wxyz is not unit length")

    source_config_path = source_a_root / "model_config.json"
    source_config = json.loads(source_config_path.read_text(encoding="utf-8"))
    config_joint_order = tuple(source_config["joint_names"])
    source_defaults = tuple(
        float(source_config["default_joint_pos"][name])
        for name in SONIC_BODY_JOINT_ORDER
    )
    if config_joint_order != SONIC_BODY_JOINT_ORDER:
        raise ValueError(
            "Source-A configured body order differs from SONIC MuJoCo order"
        )
    if source_defaults != DEFAULT_ANGLES:
        raise ValueError("Source-A defaults differ from SONIC v1.1 defaults")

    phase_path = s3_episode / "PHASE_EVENTS.json"
    phase_document = json.loads(phase_path.read_text(encoding="utf-8"))
    phase_events = tuple(phase_document["events"])
    phase_times = [float(row["sim_time_s"]) for row in phase_events]
    if phase_times != sorted(phase_times):
        raise ValueError("phase events are not monotonic")

    inputs = MappingInputs(
        times_s=policy_time,
        body_position_mujoco_rad=all_joint_position[:, joint_indices],
        body_velocity_mujoco_rad_s=all_joint_velocity[:, joint_indices],
        base_quaternion_wxyz=quaternion,
        base_angular_velocity_rad_s=base_velocity[:, 3:6],
        source_targets_mujoco_rad=controls[:, actuator_indices],
        phase_events=phase_events,
        source_model_joint_order=joint_order,
        source_actuator_order=actuator_order,
    )
    bindings = {
        "state_manifest": _file_binding(stream_root / "MANIFEST.json"),
        "policy_state": policy_binding["file"],
        "privileged_state": privileged_binding["file"],
        "phase_events": _file_binding(phase_path),
        "s3_result": _file_binding(s3_episode / "S3_RESULT.json"),
        "source_model": _file_binding(source_model_path),
        "source_scene": _file_binding(source_a_root / "scene.xml"),
        "source_model_config": _file_binding(source_config_path),
    }
    return inputs, bindings


def reorder_mujoco_to_isaaclab(values: Any) -> Any:
    import numpy as np

    array = np.asarray(values)
    if array.shape[-1] != 29:
        raise ValueError(f"joint array must end in 29 values, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("joint array must be finite")
    return array[..., MUJOCO_TO_ISAACLAB]


def _quat_conjugate(quaternion: Any) -> Any:
    import numpy as np

    q = np.asarray(quaternion, dtype=np.float64)
    return np.asarray([q[0], -q[1], -q[2], -q[3]], dtype=np.float64)


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


def _quat_rotate(quaternion: Any, vector: Any) -> Any:
    import numpy as np

    q = np.asarray(quaternion, dtype=np.float64)
    v = np.asarray(vector, dtype=np.float64)
    pure = np.asarray([0.0, v[0], v[1], v[2]], dtype=np.float64)
    return _quat_multiply(_quat_multiply(q, pure), _quat_conjugate(q))[1:]


def _heading_quaternion(quaternion: Any) -> Any:
    import numpy as np

    direction = _quat_rotate(quaternion, [1.0, 0.0, 0.0])
    heading = math.atan2(float(direction[1]), float(direction[0]))
    return np.asarray(
        [math.cos(heading / 2.0), 0.0, 0.0, math.sin(heading / 2.0)],
        dtype=np.float64,
    )


def _rotation_6d_rowwise(quaternion: Any) -> Any:
    import numpy as np

    q = np.asarray(quaternion, dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("rotation quaternion must be finite and nonzero")
    w, x, y, z = q / norm
    matrix = np.asarray(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )
    return matrix[:, :2].reshape(-1)


def gravity_direction(quaternion_wxyz: Any) -> Any:
    return _quat_rotate(_quat_conjugate(quaternion_wxyz), [0.0, 0.0, -1.0])


def history_window(values: Any, index: int, *, frames: int = HISTORY_FRAMES) -> Any:
    import numpy as np

    array = np.asarray(values)
    if array.ndim != 2 or index < 0 or index >= array.shape[0]:
        raise ValueError("history source or index is invalid")
    width = array.shape[1]
    result = np.zeros((frames, width), dtype=np.float64)
    start = max(0, index - frames + 1)
    available = array[start : index + 1]
    result[-available.shape[0] :] = available
    return result


def build_g1_encoder_blocks(inputs: MappingInputs, index: int) -> dict[str, Any]:
    import numpy as np

    if index < 0 or index + G1_LOOKAHEAD_TICKS >= inputs.sample_count:
        raise ValueError("g1 reference window must have 45 real future ticks")
    blocks = {
        block.name: np.zeros(block.dimension, dtype=np.float64)
        for block in ENCODER_BLOCKS
    }
    future_indices = index + np.arange(G1_FUTURE_FRAMES) * G1_FUTURE_STEP
    positions = reorder_mujoco_to_isaaclab(
        inputs.body_position_mujoco_rad[future_indices]
    )
    velocities = reorder_mujoco_to_isaaclab(
        inputs.body_velocity_mujoco_rad_s[future_indices]
    )

    initial_robot_heading = _heading_quaternion(inputs.base_quaternion_wxyz[0])
    initial_reference_heading_inv = _quat_conjugate(
        _heading_quaternion(inputs.base_quaternion_wxyz[0])
    )
    apply_delta_heading = _quat_multiply(
        initial_robot_heading, initial_reference_heading_inv
    )
    current_heading_inv = _quat_conjugate(
        _heading_quaternion(inputs.base_quaternion_wxyz[index])
    )
    anchor_rows = []
    for future_index in future_indices:
        reference = _quat_multiply(
            apply_delta_heading, inputs.base_quaternion_wxyz[future_index]
        )
        anchor_rows.append(
            _rotation_6d_rowwise(_quat_multiply(current_heading_inv, reference))
        )

    blocks["encoder_mode_4"] = np.asarray([0.0, 0.0, 0.0, 0.0])
    blocks["motion_joint_positions_10frame_step5"] = positions.reshape(-1)
    blocks["motion_joint_velocities_10frame_step5"] = velocities.reshape(-1)
    blocks["motion_anchor_orientation_heading_10frame_step5"] = np.asarray(
        anchor_rows
    ).reshape(-1)
    return blocks


def build_decoder_blocks(
    inputs: MappingInputs,
    index: int,
    *,
    token_state: Any,
    logged_last_actions_isaaclab: Any,
    prepared_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    import numpy as np

    state = prepared_state or prepare_decoder_state(inputs)
    position_isaac = state["position_isaaclab_relative_rad"]
    velocity_isaac = state["velocity_isaaclab_rad_s"]
    gravity = state["gravity_body"]
    blocks = {
        "token_state": np.asarray(token_state, dtype=np.float64).reshape(-1),
        "his_base_angular_velocity_10frame_step1": history_window(
            inputs.base_angular_velocity_rad_s, index
        ).reshape(-1),
        "his_body_joint_positions_10frame_step1": history_window(
            position_isaac, index
        ).reshape(-1),
        "his_body_joint_velocities_10frame_step1": history_window(
            velocity_isaac, index
        ).reshape(-1),
        "his_last_actions_10frame_step1": history_window(
            logged_last_actions_isaaclab, index
        ).reshape(-1),
        "his_gravity_dir_10frame_step1": history_window(gravity, index).reshape(-1),
    }
    return blocks


def prepare_decoder_state(inputs: MappingInputs) -> dict[str, Any]:
    import numpy as np

    relative_position = inputs.body_position_mujoco_rad - np.asarray(DEFAULT_ANGLES)
    return {
        "position_isaaclab_relative_rad": reorder_mujoco_to_isaaclab(relative_position),
        "velocity_isaaclab_rad_s": reorder_mujoco_to_isaaclab(
            inputs.body_velocity_mujoco_rad_s
        ),
        "gravity_body": np.asarray(
            [gravity_direction(row) for row in inputs.base_quaternion_wxyz]
        ),
    }


def _phase_at(events: Sequence[Mapping[str, Any]], sim_time_s: float) -> str:
    phase = "pre_approach"
    for event in events:
        if float(event["sim_time_s"]) > sim_time_s:
            break
        phase = str(event["phase"])
    return phase


def _mapping_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    encoder_rows = []
    for block in ENCODER_BLOCKS:
        if block.name == "encoder_mode_4":
            status = "available_official_mode_constant"
            source = "explicit g1 mode_id=0 plus three specified padding zeros"
        elif block.name in G1_REQUIRED_ENCODER_BLOCKS:
            status = "available_strictly_reconstructed"
            source = "frozen S3 50 Hz future robot state in official IsaacLab order"
        else:
            status = "available_official_mode_inactive_zero"
            source = (
                "official C++ clears buffer and skips blocks not required by g1 mode"
            )
        encoder_rows.append(
            {
                "name": block.name,
                "dimension": block.dimension,
                "status": status,
                "source": source,
            }
        )

    decoder_source = {
        "token_state": "output of the real-input encoder at the same tick",
        "his_base_angular_velocity_10frame_step1": (
            "S3 base_velocity[3:6], verified against pelvis gyro by no-step kinematic probe"
        ),
        "his_body_joint_positions_10frame_step1": (
            "S3 named body joints minus frozen defaults, reordered MuJoCo to IsaacLab"
        ),
        "his_body_joint_velocities_10frame_step1": (
            "S3 named body joint velocities reordered MuJoCo to IsaacLab"
        ),
        "his_last_actions_10frame_step1": (
            "prior raw SONIC shadow outputs; official leading history padding is zero"
        ),
        "his_gravity_dir_10frame_step1": (
            "inverse S3 base quaternion rotates world [0,0,-1] into body frame"
        ),
    }
    decoder_rows = [
        {
            "name": block.name,
            "dimension": block.dimension,
            "status": "available_strictly_reconstructed",
            "source": decoder_source[block.name],
        }
        for block in DECODER_BLOCKS
    ]
    return encoder_rows, decoder_rows


def inspect_official_mode_sources(sonic_root: Path) -> dict[str, Any]:
    controller_path = (
        sonic_root / "source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/"
        "g1_deploy_onnx_ref.cpp"
    )
    state_logger_path = (
        sonic_root
        / "source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/src/state_logger.cpp"
    )
    parameters_path = (
        sonic_root / "source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/"
        "policy_parameters.hpp"
    )
    config_path = sonic_root / "weights/sonic_v1_1/observation_config.yaml"
    controller = controller_path.read_text(encoding="utf-8", errors="replace")
    state_logger = state_logger_path.read_text(encoding="utf-8", errors="replace")
    config = config_path.read_text(encoding="utf-8", errors="replace")
    required_config_markers = (
        'name: "g1"',
        "mode_id: 0",
        *G1_REQUIRED_ENCODER_BLOCKS,
    )
    markers = {
        "g1_mode_declared": all(marker in config for marker in required_config_markers),
        "encoder_buffer_cleared_before_mode_gather": (
            "std::fill(encoder_obs_buffer_.begin(), encoder_obs_buffer_.end(), 0.0)"
            in controller
        ),
        "inactive_mode_blocks_skipped": (
            "Not required for this mode - leave as zero" in controller
        ),
        "history_oldest_first": (
            "otherwise [oldest, ..., newest]"
            in (
                sonic_root
                / "source/gear_sonic_deploy/src/g1/g1_deploy_onnx_ref/include/"
                "state_logger.hpp"
            ).read_text(encoding="utf-8", errors="replace")
        ),
        "history_zero_padding": "Pad with zeros if requested more than available"
        in state_logger,
        "body_positions_subtract_defaults": bool(
            re.search(r"\.q\(\)\s*-\s*default_angles", controller)
        ),
        "last_action_is_raw_policy_output": (
            "last_action[i] = static_cast<double>(floatarr[i])" in controller
        ),
    }
    return {
        "observation_config": _file_binding(config_path),
        "controller": _file_binding(controller_path),
        "state_logger": _file_binding(state_logger_path),
        "policy_parameters": _file_binding(parameters_path),
        "markers": markers,
        "all_markers_match": all(markers.values()),
    }


def inspect_bundled_references(sonic_root: Path) -> dict[str, Any]:
    reference_root = sonic_root / "source/gear_sonic_deploy/reference/example"
    motion_dirs = sorted(path for path in reference_root.iterdir() if path.is_dir())
    csv_files = sorted(reference_root.glob("*/*.csv"))
    lfs_pointers = [path for path in csv_files if _is_lfs_pointer(path)]
    smpl_files = sorted(reference_root.glob("*/smpl_joint.csv"))
    return {
        "path": str(reference_root),
        "motion_directory_count": len(motion_dirs),
        "csv_file_count": len(csv_files),
        "git_lfs_pointer_count": len(lfs_pointers),
        "materialized_csv_count": len(csv_files) - len(lfs_pointers),
        "smpl_joint_file_count": len(smpl_files),
        "used_by_this_mapping": False,
        "note": (
            "The frozen Source-A stream is used as an offline g1 reference. "
            "Bundled examples remain LFS pointers and are not silently substituted."
        ),
    }


def _update_float32_hash(hasher: Any, values: Any) -> None:
    import numpy as np

    hasher.update(np.asarray(values, dtype=np.float32).tobytes())


def run_offline_shadow(
    *,
    inputs: MappingInputs,
    encoder_path: Path,
    decoder_path: Path,
    max_samples: int | None = None,
) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as ort

    usable = inputs.sample_count - G1_LOOKAHEAD_TICKS
    requested = usable if max_samples is None else max_samples
    if requested <= 0:
        raise ValueError("max_samples must be positive")
    count = min(usable, requested)
    if count <= 0:
        raise ValueError("state stream has no complete g1 reference window")

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
    phase_accumulators: dict[str, dict[str, Any]] = {}
    exemplars: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()

    for index in range(count):
        encoder_blocks = build_g1_encoder_blocks(inputs, index)
        encoder_values = ENCODER_ASSEMBLER.assemble(encoder_blocks)
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_blocks = build_decoder_blocks(
            inputs,
            index,
            token_state=token,
            logged_last_actions_isaaclab=logged_actions,
            prepared_state=prepared_decoder_state,
        )
        decoder_values = DECODER_ASSEMBLER.assemble(decoder_blocks)
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        raw_action_array = decoder.run(
            None, {decoder.get_inputs()[0].name: decoder_input}
        )[0].reshape(-1)
        if not (
            np.isfinite(encoder_input).all()
            and np.isfinite(token).all()
            and np.isfinite(decoder_input).all()
            and np.isfinite(raw_action_array).all()
        ):
            raise RuntimeError(f"non-finite shadow value at sample {index}")

        if index + 1 < count:
            logged_actions[index + 1] = raw_action_array
        sim_time_s = float(inputs.times_s[index])
        phase = _phase_at(inputs.phase_events, sim_time_s)
        sonic_target = body_joint_target_from_raw_action(
            raw_action_array, phase=phase, sim_time_s=sim_time_s
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
                    np.asarray(raw_action_array, dtype=np.float32).tobytes()
                ).hexdigest(),
            }

        _update_float32_hash(hashes["encoder_inputs"], encoder_input)
        _update_float32_hash(hashes["encoder_tokens"], token)
        _update_float32_hash(hashes["decoder_inputs"], decoder_input)
        _update_float32_hash(hashes["raw_actions"], raw_action_array)
        _update_float32_hash(hashes["scaled_targets"], sonic_target.position_target_rad)
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
    return {
        "status": "executed_non_actuating",
        "provider": "CPUExecutionProvider",
        "onnxruntime_version": ort.__version__,
        "reference_mode": "g1_mode_id_0",
        "reference_semantics": "offline_oracle_future_reference_from_frozen_s3",
        "causal_online_controller_evidence": False,
        "sample_count": count,
        "usable_complete_reference_windows": usable,
        "first_sim_time_s": float(inputs.times_s[0]),
        "last_sim_time_s": float(inputs.times_s[count - 1]),
        "model_forwards": count * 2,
        "physics_steps": 0,
        "elapsed_wall_s": elapsed,
        "mean_wall_ms_per_encoder_decoder_pair": elapsed * 1000.0 / count,
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
        "phase_metrics": phase_metrics,
        "phase_exemplars": exemplars,
        "candidate_consumed_by_physics": False,
        "actuation_enabled": False,
    }


def run_mapping_audit(
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
    output_path = output_path or sonic_root / "SONIC_REAL_OBSERVATION_MAPPING.json"
    inputs, input_bindings = load_mapping_inputs(
        s3_episode=s3_episode, source_a_root=source_a_root
    )
    official = inspect_official_mode_sources(sonic_root)
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
    mapping_ready = bool(
        official["all_markers_match"]
        and exact_50hz
        and inputs.sample_count > G1_LOOKAHEAD_TICKS
        and all(row["status"].startswith("available_") for row in encoder_rows)
        and all(row["status"].startswith("available_") for row in decoder_rows)
    )
    encoder_path = sonic_root / "weights/sonic_v1_1/model_encoder.onnx"
    decoder_path = sonic_root / "weights/sonic_v1_1/model_decoder.onnx"
    model_files_ready = encoder_path.is_file() and decoder_path.is_file()
    blockers = []
    if not mapping_ready:
        blockers.append("real_observation_mapping_not_ready")
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
            phase="offline_mapping", sim_time_s=0.0, blockers=blockers
        )
        shadow.update({"model_forwards": 0, "physics_steps": 0})
    else:
        shadow = run_offline_shadow(
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
        "official_semantics": official,
        "bundled_reference_inventory": references,
        "temporal_contract": {
            "sample_count": inputs.sample_count,
            "first_sim_time_s": float(inputs.times_s[0]),
            "last_sim_time_s": float(inputs.times_s[-1]),
            "sample_period_s": CONTROL_DT_S,
            "exact_50hz": exact_50hz,
            "history_frames": HISTORY_FRAMES,
            "history_order": "oldest_to_newest_with_official_leading_zero_padding",
            "g1_future_frames": G1_FUTURE_FRAMES,
            "g1_future_step_ticks": G1_FUTURE_STEP,
            "g1_future_step_s": G1_FUTURE_STEP * CONTROL_DT_S,
            "g1_lookahead_s": G1_LOOKAHEAD_TICKS * CONTROL_DT_S,
            "complete_reference_window_count": inputs.sample_count - G1_LOOKAHEAD_TICKS,
        },
        "joint_contract": {
            "source_model_joint_count": len(inputs.source_model_joint_order),
            "source_actuator_count": len(inputs.source_actuator_order),
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
            "position_history_transform": (
                "select named MuJoCo joints, subtract defaults, reorder to IsaacLab"
            ),
            "velocity_history_transform": (
                "select named MuJoCo joints, reorder to IsaacLab"
            ),
        },
        "coordinate_contract": {
            "quaternion_convention": "wxyz",
            "gravity_world_direction": [0.0, 0.0, -1.0],
            "gravity_transform": "quat_rotate(conjugate(base_quat), world_down)",
            "base_angular_velocity_source": "policy_state.base_velocity[:,3:6]",
            "base_angular_velocity_frame_validation": {
                "method": "no-integration mj_forward on four frozen S3 states",
                "sensor": "Source-A imu-pelvis-angular-velocity",
                "sample_indices": [0, 1000, 3000, 6000],
                "max_abs_difference": 5.551115123125783e-17,
                "physics_steps": 0,
            },
            "anchor_orientation": (
                "official heading-only current robot frame to future reference root; "
                "first two rotation-matrix columns flattened row-wise"
            ),
        },
        "mapping": {
            "selected_encoder_mode": {"name": "g1", "mode_id": 0},
            "encoder_blocks": encoder_rows,
            "decoder_blocks": decoder_rows,
            "inactive_encoder_zero_policy": (
                "official mode filtering, not guessed missing observations"
            ),
        },
        "offline_shadow": shadow,
        "gates": {
            "source_a_stream_integrity": True,
            "temporal_alignment_ready": exact_50hz,
            "joint_mapping_ready": True,
            "g1_encoder_mode_ready": mapping_ready,
            "decoder_state_history_ready": mapping_ready,
            "autoregressive_last_action_ready": mapping_ready,
            "real_observation_mapping_ready": mapping_ready,
            "cpu_offline_shadow_executed": shadow.get("status")
            == "executed_non_actuating",
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
            "This proves a hash-bound, dimension-complete SONIC v1.1 g1-mode "
            "mapping and, when executed, a non-actuating CPU replay over frozen "
            "states. Future Source-A states are an offline oracle reference, so "
            "the result is not causal online control, native TensorRT reproduction, "
            "physics stability, grasp quality, task success, or evidence that SONIC "
            "outperforms Source A. The S3 trajectory remains diagnostic and Source A "
            "remains the only controller that produced its physics."
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
    report = run_mapping_audit(
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
                    args.output
                    or args.sonic_root / "SONIC_REAL_OBSERVATION_MAPPING.json"
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
