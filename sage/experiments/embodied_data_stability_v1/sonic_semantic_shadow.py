"""CPU-only semantic SONIC v1.1 observation and action shadow.

This module mirrors the frozen v1.1 observation block order and the official
29-body-joint action transform.  It deliberately exposes no simulator or
actuator method.  The executable smoke uses synthetic finite inputs only; its
purpose is to prove named-block assembly, model chaining, and action scaling.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .sonic_shadow import (
    SONIC_ACTION_DIM,
    SONIC_BODY_JOINT_ORDER,
    BodyJointTarget,
)


SCHEMA = "sonic-cpu-semantic-shadow/v1"


@dataclass(frozen=True)
class ObservationBlock:
    name: str
    dimension: int


ENCODER_BLOCKS = (
    ObservationBlock("encoder_mode_4", 4),
    ObservationBlock("motion_joint_positions_10frame_step5", 290),
    ObservationBlock("motion_joint_velocities_10frame_step5", 290),
    ObservationBlock("motion_anchor_orientation_heading_10frame_step5", 60),
    ObservationBlock("motion_anchor_orientation_heading", 6),
    ObservationBlock("motion_joint_positions_lowerbody_10frame_step5", 120),
    ObservationBlock("motion_joint_velocities_lowerbody_10frame_step5", 120),
    ObservationBlock("vr_3point_local_target", 9),
    ObservationBlock("vr_3point_local_orn_target", 12),
    ObservationBlock("smpl_joints_10frame_step1", 720),
    ObservationBlock("smpl_anchor_orientation_heading_10frame_step1", 60),
    ObservationBlock("motion_joint_positions_wrists_10frame_step1", 60),
)

DECODER_BLOCKS = (
    ObservationBlock("token_state", 64),
    ObservationBlock("his_base_angular_velocity_10frame_step1", 30),
    ObservationBlock("his_body_joint_positions_10frame_step1", 290),
    ObservationBlock("his_body_joint_velocities_10frame_step1", 290),
    ObservationBlock("his_last_actions_10frame_step1", 290),
    ObservationBlock("his_gravity_dir_10frame_step1", 30),
)

ENCODER_DIMENSION = sum(block.dimension for block in ENCODER_BLOCKS)
DECODER_DIMENSION = sum(block.dimension for block in DECODER_BLOCKS)

ISAACLAB_TO_MUJOCO = (
    0,
    3,
    6,
    9,
    13,
    17,
    1,
    4,
    7,
    10,
    14,
    18,
    2,
    5,
    8,
    11,
    15,
    19,
    21,
    23,
    25,
    27,
    12,
    16,
    20,
    22,
    24,
    26,
    28,
)

DEFAULT_ANGLES = (
    -0.312,
    0.0,
    0.0,
    0.669,
    -0.363,
    0.0,
    -0.312,
    0.0,
    0.0,
    0.669,
    -0.363,
    0.0,
    0.0,
    0.0,
    0.0,
    0.2,
    0.2,
    0.0,
    0.6,
    0.0,
    0.0,
    0.0,
    0.2,
    -0.2,
    0.0,
    0.6,
    0.0,
    0.0,
    0.0,
)

NATURAL_FREQUENCY = 10.0 * 2.0 * 3.1415926535
MOTOR_PARAMETERS = {
    "5020": {"armature": 0.003609725, "effort_limit": 25.0},
    "7520_14": {"armature": 0.010177520, "effort_limit": 88.0},
    "7520_22": {"armature": 0.025101925, "effort_limit": 139.0},
    "4010": {"armature": 0.00425, "effort_limit": 5.0},
}
ACTION_MOTOR_TYPES = (
    "7520_22",
    "7520_22",
    "7520_14",
    "7520_22",
    "5020",
    "5020",
    "7520_22",
    "7520_22",
    "7520_14",
    "7520_22",
    "5020",
    "5020",
    "7520_14",
    "5020",
    "5020",
    "5020",
    "5020",
    "5020",
    "5020",
    "5020",
    "4010",
    "4010",
    "5020",
    "5020",
    "5020",
    "5020",
    "5020",
    "4010",
    "4010",
)


def _action_scale(motor_type: str) -> float:
    parameters = MOTOR_PARAMETERS[motor_type]
    stiffness = parameters["armature"] * NATURAL_FREQUENCY * NATURAL_FREQUENCY
    return 0.25 * parameters["effort_limit"] / stiffness


ACTION_SCALES = tuple(_action_scale(name) for name in ACTION_MOTOR_TYPES)


def _finite_vector(
    values: Iterable[float],
    *,
    dimension: int,
    label: str,
) -> tuple[float, ...]:
    result = tuple(float(value) for value in values)
    if len(result) != dimension:
        raise ValueError(f"{label} must contain {dimension} values, got {len(result)}")
    if not all(math.isfinite(value) for value in result):
        raise ValueError(f"{label} must contain only finite values")
    return result


class NamedObservationAssembler:
    """Concatenate named, finite blocks in one frozen model-input order."""

    def __init__(self, blocks: Sequence[ObservationBlock], label: str):
        self.blocks = tuple(blocks)
        self.label = label
        names = [block.name for block in self.blocks]
        if len(names) != len(set(names)):
            raise ValueError(f"{label} contains duplicate block names")
        if any(block.dimension <= 0 for block in self.blocks):
            raise ValueError(f"{label} contains a non-positive block dimension")
        self.dimension = sum(block.dimension for block in self.blocks)

    def layout(self) -> list[dict[str, Any]]:
        offset = 0
        rows = []
        for block in self.blocks:
            rows.append(
                {
                    "name": block.name,
                    "offset": offset,
                    "dimension": block.dimension,
                    "end_exclusive": offset + block.dimension,
                }
            )
            offset += block.dimension
        return rows

    def assemble(
        self,
        values: Mapping[str, Iterable[float]],
    ) -> tuple[float, ...]:
        expected = {block.name for block in self.blocks}
        actual = set(values)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            raise ValueError(
                f"{self.label} block mismatch; missing={missing}, extra={extra}"
            )
        assembled: list[float] = []
        for block in self.blocks:
            assembled.extend(
                _finite_vector(
                    values[block.name],
                    dimension=block.dimension,
                    label=f"{self.label}.{block.name}",
                )
            )
        return tuple(assembled)


ENCODER_ASSEMBLER = NamedObservationAssembler(ENCODER_BLOCKS, "encoder")
DECODER_ASSEMBLER = NamedObservationAssembler(DECODER_BLOCKS, "decoder")


def parse_v11_config_order(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        policy_section = text.split("observations:", 1)[1].split("encoder:", 1)[0]
        encoder_section = text.split("encoder_observations:", 1)[1].split(
            "encoder_modes:", 1
        )[0]
    except IndexError as exc:
        raise ValueError(f"unrecognized observation config structure: {path}") from exc
    enabled_pattern = re.compile(
        r'-\s+name:\s*["\']?([^"\'\n]+?)["\']?\s*\n\s+enabled:\s*true\s*$',
        flags=re.MULTILINE,
    )
    policy = [name.strip() for name in enabled_pattern.findall(policy_section)]
    encoder = [name.strip() for name in enabled_pattern.findall(encoder_section)]
    expected_policy = [block.name for block in DECODER_BLOCKS]
    expected_encoder = [block.name for block in ENCODER_BLOCKS]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "policy_enabled_order": policy,
        "encoder_enabled_order": encoder,
        "expected_policy_order": expected_policy,
        "expected_encoder_order": expected_encoder,
        "policy_order_matches": policy == expected_policy,
        "encoder_order_matches": encoder == expected_encoder,
        "encoder_dimension": ENCODER_DIMENSION,
        "decoder_dimension": DECODER_DIMENSION,
    }


def scale_action_to_mujoco_targets(
    raw_action_isaaclab: Iterable[float],
) -> tuple[float, ...]:
    raw = _finite_vector(
        raw_action_isaaclab,
        dimension=SONIC_ACTION_DIM,
        label="raw_action_isaaclab",
    )
    return tuple(
        DEFAULT_ANGLES[mujoco_index]
        + raw[ISAACLAB_TO_MUJOCO[mujoco_index]] * ACTION_SCALES[mujoco_index]
        for mujoco_index in range(SONIC_ACTION_DIM)
    )


def body_joint_target_from_raw_action(
    raw_action_isaaclab: Iterable[float],
    *,
    phase: str,
    sim_time_s: float,
) -> BodyJointTarget:
    return BodyJointTarget(
        controller_id="sonic_v1_1_cpu_shadow",
        phase=phase,
        sim_time_s=sim_time_s,
        joint_order=SONIC_BODY_JOINT_ORDER,
        position_target_rad=scale_action_to_mujoco_targets(raw_action_isaaclab),
    ).validated()


def inspect_official_semantic_sources(source_root: Path) -> dict[str, Any]:
    base = source_root / "gear_sonic_deploy/src/g1/g1_deploy_onnx_ref"
    parameters = base / "include/policy_parameters.hpp"
    controller = base / "src/g1_deploy_onnx_ref.cpp"
    parameter_text = parameters.read_text(encoding="utf-8", errors="replace")
    controller_text = controller.read_text(encoding="utf-8", errors="replace")
    required_markers = {
        "official_action_formula": (
            "floatarr[isaaclab_to_mujoco[i]]) * g1_action_scale[i]" in controller_text
        ),
        "default_angle_offset": ("default_angles[i] + action_value" in controller_text),
        "raw_last_action_history": (
            "last_action[i] = static_cast<double>(floatarr[i])" in controller_text
        ),
        "action_scale_formula": ("0.25 * effort_limit / stiffness" in parameter_text),
        "isaaclab_mapping_declared": (
            "const std::array<int, 29> isaaclab_to_mujoco" in parameter_text
        ),
        "default_angles_declared": (
            "const std::array<double, 29> default_angles" in parameter_text
        ),
    }
    observation_markers: dict[str, bool] = {}
    for block in (*ENCODER_BLOCKS, *DECODER_BLOCKS):
        dimension_expression = (
            r"token_dim" if block.name == "token_state" else str(block.dimension)
        )
        marker = re.compile(
            r'\{"' + re.escape(block.name) + r'",\s*' + dimension_expression + r","
        )
        observation_markers[block.name] = marker.search(controller_text) is not None
    return {
        "policy_parameters_path": str(parameters),
        "policy_parameters_sha256": sha256_file(parameters),
        "controller_path": str(controller),
        "controller_sha256": sha256_file(controller),
        "required_markers": required_markers,
        "observation_registry_markers": observation_markers,
        "required_markers_match": all(required_markers.values()),
        "observation_registry_matches": all(observation_markers.values()),
    }


def _float32_sha256(array: Any) -> str:
    return hashlib.sha256(array.tobytes()).hexdigest()


def run_cpu_semantic_smoke(
    *,
    encoder_path: Path,
    decoder_path: Path,
) -> dict[str, Any]:
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        return {"executed": False, "error": str(exc), "model_forwards": 0}

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    encoder = ort.InferenceSession(
        str(encoder_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    decoder = ort.InferenceSession(
        str(decoder_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )

    encoder_blocks = {block.name: [0.0] * block.dimension for block in ENCODER_BLOCKS}
    encoder_blocks["encoder_mode_4"][0] = 0.0
    encoder_values = ENCODER_ASSEMBLER.assemble(encoder_blocks)
    encoder_input = np.asarray([encoder_values], dtype=np.float32)
    encoder_output = encoder.run(
        None,
        {encoder.get_inputs()[0].name: encoder_input},
    )[0]

    decoder_blocks = {block.name: [0.0] * block.dimension for block in DECODER_BLOCKS}
    decoder_blocks["token_state"] = encoder_output.reshape(-1).tolist()
    decoder_values = DECODER_ASSEMBLER.assemble(decoder_blocks)
    decoder_input = np.asarray([decoder_values], dtype=np.float32)
    action = decoder.run(
        None,
        {decoder.get_inputs()[0].name: decoder_input},
    )[0]
    action_values = action.reshape(-1).tolist()
    target = body_joint_target_from_raw_action(
        action_values,
        phase="semantic_preflight",
        sim_time_s=0.0,
    )
    zero_target = scale_action_to_mujoco_targets([0.0] * SONIC_ACTION_DIM)
    return {
        "executed": True,
        "provider": "CPUExecutionProvider",
        "onnxruntime_version": ort.__version__,
        "input_kind": "synthetic_zero_blocks_with_encoder_token_chaining",
        "encoder_input_shape": list(encoder_input.shape),
        "encoder_input_sha256": _float32_sha256(encoder_input),
        "encoder_output_shape": list(encoder_output.shape),
        "encoder_output_sha256": _float32_sha256(encoder_output),
        "encoder_output_all_finite": bool(np.isfinite(encoder_output).all()),
        "decoder_input_shape": list(decoder_input.shape),
        "decoder_input_sha256": _float32_sha256(decoder_input),
        "raw_action_shape": list(action.shape),
        "raw_action_sha256": _float32_sha256(action),
        "raw_action_all_finite": bool(np.isfinite(action).all()),
        "scaled_target_all_finite": all(
            math.isfinite(value) for value in target.position_target_rad
        ),
        "scaled_target_rad": list(target.position_target_rad),
        "zero_action_maps_to_default_angles": zero_target == DEFAULT_ANGLES,
        "candidate_consumed_by_physics": False,
        "actuation_enabled": False,
        "model_forwards": 2,
        "physics_steps": 0,
    }


def action_contract_report() -> dict[str, Any]:
    basis_checks = []
    for mujoco_index, isaaclab_index in enumerate(ISAACLAB_TO_MUJOCO):
        action = [0.0] * SONIC_ACTION_DIM
        action[isaaclab_index] = 1.0
        target = scale_action_to_mujoco_targets(action)
        changed = [
            index
            for index, (actual, default) in enumerate(zip(target, DEFAULT_ANGLES))
            if actual != default
        ]
        basis_checks.append(
            {
                "mujoco_index": mujoco_index,
                "joint_name": SONIC_BODY_JOINT_ORDER[mujoco_index],
                "isaaclab_action_index": isaaclab_index,
                "scale_rad": ACTION_SCALES[mujoco_index],
                "changed_mujoco_indices": changed,
                "passed": changed == [mujoco_index]
                and target[mujoco_index]
                == DEFAULT_ANGLES[mujoco_index] + ACTION_SCALES[mujoco_index],
            }
        )
    payload = {
        "joint_order": list(SONIC_BODY_JOINT_ORDER),
        "isaaclab_to_mujoco": list(ISAACLAB_TO_MUJOCO),
        "default_angles_rad": list(DEFAULT_ANGLES),
        "action_scales_rad": list(ACTION_SCALES),
    }
    return {
        **payload,
        "contract_sha256": canonical_sha256(payload),
        "zero_action_maps_to_default_angles": scale_action_to_mujoco_targets(
            [0.0] * SONIC_ACTION_DIM
        )
        == DEFAULT_ANGLES,
        "basis_checks": basis_checks,
        "all_basis_checks_passed": all(row["passed"] for row in basis_checks),
    }


def run_semantic_preflight(
    *,
    run_root: Path,
    output_path: Path | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    run_root = run_root.resolve()
    output_path = output_path or run_root / "SONIC_CPU_SEMANTIC_SHADOW.json"
    source_root = run_root / "source"
    config_path = run_root / "weights/sonic_v1_1/observation_config.yaml"
    config = parse_v11_config_order(config_path)
    sources = inspect_official_semantic_sources(source_root)
    action = action_contract_report()
    smoke = run_cpu_semantic_smoke(
        encoder_path=run_root / "weights/sonic_v1_1/model_encoder.onnx",
        decoder_path=run_root / "weights/sonic_v1_1/model_decoder.onnx",
    )
    observation_ready = bool(
        ENCODER_DIMENSION == 1751
        and DECODER_DIMENSION == 994
        and config["policy_order_matches"]
        and config["encoder_order_matches"]
        and sources["observation_registry_matches"]
    )
    action_ready = bool(
        sources["required_markers_match"]
        and action["zero_action_maps_to_default_angles"]
        and action["all_basis_checks_passed"]
    )
    smoke_ready = bool(
        smoke.get("executed")
        and smoke.get("encoder_output_all_finite")
        and smoke.get("raw_action_all_finite")
        and smoke.get("scaled_target_all_finite")
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "implementation": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "source_bindings": sources,
        "observation_contract": {
            "config": config,
            "encoder_layout": ENCODER_ASSEMBLER.layout(),
            "encoder_dimension": ENCODER_DIMENSION,
            "decoder_layout": DECODER_ASSEMBLER.layout(),
            "decoder_dimension": DECODER_DIMENSION,
        },
        "action_contract": action,
        "cpu_semantic_smoke": smoke,
        "gates": {
            "semantic_observation_layout_ready": observation_ready,
            "action_scaling_ready": action_ready,
            "cpu_shadow_candidate_ready": observation_ready
            and action_ready
            and smoke_ready,
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
            "model_forwards": smoke.get("model_forwards", 0),
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
        },
        "claim_boundary": (
            "This preflight proves the frozen named-block layout, exact dimensions, "
            "CPU encoder-to-decoder chaining on synthetic zero blocks, and the "
            "official 29-joint reorder/scale/offset transform. It does not prove "
            "that real robot histories or reference motions have been populated "
            "correctly, and it is not behavior, physics, grasp, stability, or "
            "task-success evidence. Source A remains the only controller permitted "
            "to drive existing physics paths."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_path, report)
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--observed-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_semantic_preflight(
        run_root=args.run_root,
        output_path=args.output,
        observed_at=args.observed_at,
    )
    print(
        json.dumps(
            {
                "output": str(
                    args.output or args.run_root / "SONIC_CPU_SEMANTIC_SHADOW.json"
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
