"""Diagnose SONIC causal-hold discontinuities without physics or actuation.

Three bounded CPU shadows separate two hypotheses:

* causal hold + official autoregressive action history (the candidate),
* causal hold + zero action history (a non-deployable feedback ablation), and
* recorded future state + official action history (an explicitly non-causal
  reference-context ablation).

The run stops after the two previously identified discontinuities.  It also
freezes an empirical command-continuity non-regression gate from the Source-A
S3 trajectory.  That gate is for admission on this frozen task, not a hardware
limit, and it never clips or alters a candidate action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_causal_hold_shadow import build_causal_hold_encoder_blocks
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    DEFAULT_S3_EPISODE,
    DEFAULT_SONIC_RUN,
    DEFAULT_SOURCE_A,
    G1_FUTURE_FRAMES,
    G1_FUTURE_STEP,
    G1_LOOKAHEAD_TICKS,
    MappingInputs,
    _file_binding,
    _phase_at,
    _update_float32_hash,
    build_decoder_blocks,
    build_g1_encoder_blocks,
    load_mapping_inputs,
    prepare_decoder_state,
    reorder_mujoco_to_isaaclab,
)
from .sonic_semantic_shadow import (
    ACTION_SCALES,
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import SONIC_BODY_JOINT_ORDER


SCHEMA = "sonic-causal-reference-diagnostic/v2"
DIAGNOSTIC_TO_INDICES = (429, 2270)
DEFAULT_SAMPLE_COUNT = max(DIAGNOSTIC_TO_INDICES) + 1
PERCENTILES = (50.0, 95.0, 99.0, 99.9, 99.99, 100.0)
NUMERIC_TOLERANCE_RAD = 1e-6
TAKEOVER_QUALIFICATION_TICKS = 50
PROJECTION_VELOCITY_HISTORY_FRAMES = 10
PROJECTION_DECAY_TIME_CONSTANT_S = 0.1
VARIANTS = (
    {
        "name": "causal_hold_autoregressive",
        "reference": "causal_hold",
        "action_history": "autoregressive",
        "causal": True,
        "deployable_semantics": True,
    },
    {
        "name": "causal_measured_state_hold_autoregressive",
        "reference": "causal_measured_state_hold",
        "action_history": "autoregressive",
        "causal": True,
        "deployable_semantics": True,
    },
    {
        "name": "causal_measured_state_hold_source_applied_history",
        "reference": "causal_measured_state_hold",
        "action_history": "source_a_applied_one_step_takeover",
        "causal": True,
        "deployable_semantics": True,
        "evaluation_semantics": "independent_one_step_takeover_proposals",
    },
    {
        "name": "causal_damped_state_projection_autoregressive",
        "reference": "causal_damped_state_projection",
        "action_history": "autoregressive",
        "causal": True,
        "deployable_semantics": True,
    },
    {
        "name": "causal_measured_state_mean10_hold_autoregressive",
        "reference": "causal_measured_state_mean10_hold",
        "action_history": "autoregressive",
        "causal": True,
        "deployable_semantics": True,
    },
    {
        "name": "causal_hold_zero_action_history",
        "reference": "causal_hold",
        "action_history": "all_zero_ablation",
        "causal": True,
        "deployable_semantics": False,
    },
    {
        "name": "future_state_oracle_autoregressive",
        "reference": "recorded_future_state_oracle",
        "action_history": "autoregressive",
        "causal": False,
        "deployable_semantics": False,
    },
)


def build_source_applied_action_history(
    inputs: MappingInputs, sample_count: int
) -> Any:
    """Reconstruct the previous action that actually produced each frozen state."""

    import numpy as np

    if sample_count <= 0 or sample_count > inputs.sample_count:
        raise ValueError("source action-history sample count is invalid")
    result = np.zeros((sample_count, 29), dtype=np.float64)
    if sample_count == 1:
        return result
    source_targets = np.asarray(
        inputs.source_targets_mujoco_rad[: sample_count - 1], dtype=np.float64
    )
    raw_mujoco = (source_targets - np.asarray(DEFAULT_ANGLES)) / np.asarray(
        ACTION_SCALES
    )
    result[1:] = reorder_mujoco_to_isaaclab(raw_mujoco)
    return result


def build_causal_measured_state_hold_encoder_blocks(
    inputs: MappingInputs, index: int
) -> dict[str, Any]:
    """Hold the current measured joints, with no future rows or target leakage."""

    import numpy as np

    blocks = build_causal_hold_encoder_blocks(inputs, index)
    current = reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[index])
    blocks["motion_joint_positions_10frame_step5"] = np.repeat(
        current[None, :], G1_FUTURE_FRAMES, axis=0
    ).reshape(-1)
    return blocks


def build_causal_damped_state_projection_encoder_blocks(
    inputs: MappingInputs, index: int
) -> dict[str, Any]:
    """Project current measured motion with a past-only, exponentially decaying velocity."""

    import numpy as np

    blocks = build_causal_hold_encoder_blocks(inputs, index)
    start = max(0, index - PROJECTION_VELOCITY_HISTORY_FRAMES + 1)
    velocity_mujoco = np.asarray(
        inputs.body_velocity_mujoco_rad_s[start : index + 1], dtype=np.float64
    ).mean(axis=0)
    current = reorder_mujoco_to_isaaclab(inputs.body_position_mujoco_rad[index])
    velocity = reorder_mujoco_to_isaaclab(velocity_mujoco)
    horizon_s = (
        np.arange(G1_FUTURE_FRAMES, dtype=np.float64) * G1_FUTURE_STEP * CONTROL_DT_S
    )
    decay = np.exp(-horizon_s / PROJECTION_DECAY_TIME_CONSTANT_S)
    displacement_scale = PROJECTION_DECAY_TIME_CONSTANT_S * (1.0 - decay)
    positions = current[None, :] + displacement_scale[:, None] * velocity[None, :]
    velocities = decay[:, None] * velocity[None, :]
    blocks["motion_joint_positions_10frame_step5"] = positions.reshape(-1)
    blocks["motion_joint_velocities_10frame_step5"] = velocities.reshape(-1)
    return blocks


def build_causal_measured_state_mean10_hold_encoder_blocks(
    inputs: MappingInputs, index: int
) -> dict[str, Any]:
    """Hold a 10-tick causal mean pose to suppress one-tick reference shocks."""

    import numpy as np

    blocks = build_causal_hold_encoder_blocks(inputs, index)
    start = max(0, index - 9)
    mean_mujoco = np.asarray(
        inputs.body_position_mujoco_rad[start : index + 1], dtype=np.float64
    ).mean(axis=0)
    mean_isaaclab = reorder_mujoco_to_isaaclab(mean_mujoco)
    blocks["motion_joint_positions_10frame_step5"] = np.repeat(
        mean_isaaclab[None, :], G1_FUTURE_FRAMES, axis=0
    ).reshape(-1)
    return blocks


def _finite_array(values: Any, *, label: str) -> Any:
    import numpy as np

    result = np.asarray(values, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != 29:
        raise ValueError(f"{label} must have shape [N,29]")
    if not np.isfinite(result).all():
        raise ValueError(f"{label} must be finite")
    return result


def continuity_metrics(values: Any) -> dict[str, Any]:
    import numpy as np

    array = _finite_array(values, label="continuity values")
    if array.shape[0] < 2:
        raise ValueError("continuity requires at least two samples")
    delta = np.diff(array, axis=0)
    absolute = np.abs(delta)
    flat = absolute.reshape(-1)
    transition, joint = np.unravel_index(int(np.argmax(absolute)), absolute.shape)
    return {
        "transition_count": int(delta.shape[0]),
        "mean_abs_delta_rad": float(absolute.mean()),
        "rms_delta_rad": float(math.sqrt(float(np.square(delta).mean()))),
        "percentiles_abs_delta_rad": {
            str(percentile): float(np.percentile(flat, percentile))
            for percentile in PERCENTILES
        },
        "global_max_abs_delta_rad": float(absolute[transition, joint]),
        "global_max_transition": {
            "from_sample_index": int(transition),
            "to_sample_index": int(transition + 1),
            "joint_index": int(joint),
            "joint_name": SONIC_BODY_JOINT_ORDER[joint],
            "signed_delta_rad": float(delta[transition, joint]),
        },
        "per_joint_max_abs_delta_rad": absolute.max(axis=0).tolist(),
    }


def _joint_command_envelope(source_a_root: Path, source_targets: Any) -> dict[str, Any]:
    import numpy as np

    root = ET.parse(source_a_root / "g1.xml").getroot()
    attributes = {
        node.attrib["name"]: node.attrib
        for node in root.findall(".//worldbody//joint")
        if node.attrib.get("name")
    }
    model_lower = []
    model_upper = []
    for name in SONIC_BODY_JOINT_ORDER:
        tokens = attributes[name].get("range", "").split()
        if len(tokens) != 2:
            raise ValueError(f"body joint has no finite range: {name}")
        model_lower.append(float(tokens[0]))
        model_upper.append(float(tokens[1]))
    values = _finite_array(source_targets, label="Source-A targets")
    model_lower_array = np.asarray(model_lower)
    model_upper_array = np.asarray(model_upper)
    source_lower = values.min(axis=0)
    source_upper = values.max(axis=0)
    admission_lower = np.minimum(model_lower_array, source_lower)
    admission_upper = np.maximum(model_upper_array, source_upper)
    return {
        "joint_order": list(SONIC_BODY_JOINT_ORDER),
        "model_joint_lower_rad": model_lower,
        "model_joint_upper_rad": model_upper,
        "source_observed_lower_rad": source_lower.tolist(),
        "source_observed_upper_rad": source_upper.tolist(),
        "admission_lower_rad": admission_lower.tolist(),
        "admission_upper_rad": admission_upper.tolist(),
        "semantics": (
            "union of model joint range and the successful frozen Source-A command envelope"
        ),
    }


def build_source_non_regression_gate(
    inputs: MappingInputs, source_a_root: Path
) -> dict[str, Any]:
    continuity = continuity_metrics(inputs.source_targets_mujoco_rad)
    envelope = _joint_command_envelope(source_a_root, inputs.source_targets_mujoco_rad)
    return {
        "name": "frozen_s3_source_a_command_non_regression",
        "scope": "same frozen task and 50 Hz command stream",
        "sample_period_s": CONTROL_DT_S,
        "all_targets_must_be_finite": True,
        "allowed_global_max_abs_delta_rad": (
            continuity["global_max_abs_delta_rad"] + NUMERIC_TOLERANCE_RAD
        ),
        "allowed_p99_9_abs_delta_rad": (
            continuity["percentiles_abs_delta_rad"]["99.9"] + NUMERIC_TOLERANCE_RAD
        ),
        "allowed_command_envelope": envelope,
        "source_baseline": continuity,
        "numeric_tolerance_rad": NUMERIC_TOLERANCE_RAD,
        "gate_is_output_modification": False,
        "claim_boundary": (
            "This is an empirical no-worse-than-Source-A replay gate, not a universal "
            "robot safety limit. A runtime guard must fail closed rather than clip a "
            "policy into apparent compliance."
        ),
    }


def evaluate_non_regression_gate(
    targets: Any, gate: Mapping[str, Any]
) -> dict[str, Any]:
    import numpy as np

    values = _finite_array(targets, label="candidate targets")
    continuity = continuity_metrics(values)
    envelope = gate["allowed_command_envelope"]
    lower = np.asarray(envelope["admission_lower_rad"], dtype=np.float64)
    upper = np.asarray(envelope["admission_upper_rad"], dtype=np.float64)
    below = values < lower[None, :] - NUMERIC_TOLERANCE_RAD
    above = values > upper[None, :] + NUMERIC_TOLERANCE_RAD
    violations = below | above
    observed_lower = values.min(axis=0)
    observed_upper = values.max(axis=0)
    below_excess = np.maximum(lower[None, :] - values, 0.0)
    above_excess = np.maximum(values - upper[None, :], 0.0)
    per_joint_violations = violations.sum(axis=0)
    checks = {
        "all_targets_finite": True,
        "global_max_slew_not_worse_than_source": (
            continuity["global_max_abs_delta_rad"]
            <= float(gate["allowed_global_max_abs_delta_rad"])
        ),
        "p99_9_slew_not_worse_than_source": (
            continuity["percentiles_abs_delta_rad"]["99.9"]
            <= float(gate["allowed_p99_9_abs_delta_rad"])
        ),
        "inside_model_or_source_command_envelope": not bool(violations.any()),
    }
    violation_rows = []
    for sample, joint in np.argwhere(violations)[:20]:
        violation_rows.append(
            {
                "sample_index": int(sample),
                "joint_index": int(joint),
                "joint_name": SONIC_BODY_JOINT_ORDER[joint],
                "target_rad": float(values[sample, joint]),
                "lower_rad": float(lower[joint]),
                "upper_rad": float(upper[joint]),
            }
        )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "continuity": continuity,
        "command_envelope_violation_count": int(violations.sum()),
        "command_envelope_by_joint": [
            {
                "joint_index": joint,
                "joint_name": SONIC_BODY_JOINT_ORDER[joint],
                "violation_count": int(per_joint_violations[joint]),
                "candidate_min_rad": float(observed_lower[joint]),
                "candidate_max_rad": float(observed_upper[joint]),
                "admission_lower_rad": float(lower[joint]),
                "admission_upper_rad": float(upper[joint]),
                "max_below_excess_rad": float(below_excess[:, joint].max()),
                "max_above_excess_rad": float(above_excess[:, joint].max()),
            }
            for joint in range(len(SONIC_BODY_JOINT_ORDER))
        ],
        "first_command_envelope_violations": violation_rows,
    }


def _true_runs(mask: Any) -> list[tuple[int, int]]:
    import numpy as np

    values = np.asarray(mask, dtype=bool).reshape(-1)
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, enabled in enumerate(values):
        if enabled and start is None:
            start = index
        elif not enabled and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(values) - 1))
    return runs


def evaluate_one_step_takeover_screen(
    targets: Any,
    source_targets: Any,
    times_s: Any,
    gate: Mapping[str, Any],
    *,
    qualification_ticks: int = TAKEOVER_QUALIFICATION_TICKS,
) -> dict[str, Any]:
    """Screen independent proposals against the command actually sent one tick earlier."""

    import numpy as np

    values = _finite_array(targets, label="takeover candidate targets")
    source = _finite_array(source_targets, label="takeover source targets")
    times = np.asarray(times_s, dtype=np.float64)
    if source.shape != values.shape or times.shape != (values.shape[0],):
        raise ValueError("takeover screen inputs have inconsistent shapes")
    if qualification_ticks <= 0:
        raise ValueError("takeover qualification ticks must be positive")

    previous_command = np.vstack([source[0], source[:-1]])
    handoff_abs_delta = np.abs(values - previous_command)
    handoff_max_by_sample = handoff_abs_delta.max(axis=1)
    handoff_limit = float(gate["allowed_global_max_abs_delta_rad"])
    handoff_ok = handoff_max_by_sample <= handoff_limit

    envelope = gate["allowed_command_envelope"]
    lower = np.asarray(envelope["admission_lower_rad"], dtype=np.float64)
    upper = np.asarray(envelope["admission_upper_rad"], dtype=np.float64)
    envelope_ok = np.logical_and(
        values >= lower[None, :] - NUMERIC_TOLERANCE_RAD,
        values <= upper[None, :] + NUMERIC_TOLERANCE_RAD,
    ).all(axis=1)
    eligible = handoff_ok & envelope_ok
    eligible[0] = False  # The frozen stream has no command row before sample zero.
    runs = _true_runs(eligible)
    qualifying = [row for row in runs if row[1] - row[0] + 1 >= qualification_ticks]
    longest = max((end - start + 1 for start, end in runs), default=0)
    worst_sample = int(np.argmax(handoff_max_by_sample))
    worst_joint = int(np.argmax(handoff_abs_delta[worst_sample]))
    return {
        "semantics": (
            "Each row is an independent causal proposal using the Source-A command "
            "that actually preceded the frozen state; this is a takeover screen, not "
            "a synthetic SONIC closed-loop rollout."
        ),
        "qualification_ticks": qualification_ticks,
        "qualification_duration_s": qualification_ticks * CONTROL_DT_S,
        "sample_zero_ineligible_without_prior_command": True,
        "eligible_sample_count": int(eligible.sum()),
        "ineligible_handoff_slew_sample_count": int((~handoff_ok).sum()),
        "ineligible_envelope_sample_count": int((~envelope_ok).sum()),
        "longest_eligible_run_ticks": longest,
        "longest_eligible_run_s": longest * CONTROL_DT_S,
        "qualifying_window_count": len(qualifying),
        "first_20_qualifying_windows": [
            {
                "start_sample_index": start,
                "end_sample_index": end,
                "tick_count": end - start + 1,
                "start_sim_time_s": float(times[start]),
                "end_sim_time_s": float(times[end]),
            }
            for start, end in qualifying[:20]
        ],
        "worst_handoff": {
            "sample_index": worst_sample,
            "sim_time_s": float(times[worst_sample]),
            "joint_index": worst_joint,
            "joint_name": SONIC_BODY_JOINT_ORDER[worst_joint],
            "abs_delta_from_previous_source_command_rad": float(
                handoff_abs_delta[worst_sample, worst_joint]
            ),
            "allowed_rad": handoff_limit,
        },
        "passed": bool(qualifying),
    }


def inspect_source_a_reference_capability(source_a_root: Path) -> dict[str, Any]:
    run_path = source_a_root / "run.py"
    sim_path = source_a_root / "ik/sim.py"
    base_path = source_a_root / "ik/base.py"
    run_text = run_path.read_text(encoding="utf-8", errors="replace")
    sim_text = sim_path.read_text(encoding="utf-8", errors="replace")
    base_text = base_path.read_text(encoding="utf-8", errors="replace")
    markers = {
        "walker_consumes_current_state_last_action_and_current_command": all(
            marker in run_text
            for marker in (
                "joint_pos, joint_vel, self.last_action, cmd",
                "action = self.walker_policy(obs)",
                "self.last_action = action.copy()",
            )
        ),
        "runner_requests_one_current_full_body_target": (
            'self.state["tp"] = self.ctrl.step()' in sim_text
        ),
        "base_navigation_exposes_goal_not_joint_trajectory": all(
            marker in base_text
            for marker in (
                "def walk_to_pose(",
                "ep.walk_to(runner, goal_xy",
            )
        ),
        "arm_has_precomputed_cartesian_joint_waypoints": all(
            marker in sim_text
            for marker in (
                "def plan_cartesian(",
                "Returns (joint solutions, endpoint residual",
                "def ramp_through(",
            )
        ),
        "arm_plan_is_only_right_arm": (
            "self.q_cmd = self.data.qpos[self.ik.qpos_idx].copy()" in sim_text
            and "for k, full_idx in enumerate(self.ctrl.right_arm_indices)" in sim_text
        ),
    }
    return {
        "bindings": {
            "controller": _file_binding(run_path),
            "simulation_and_arm_planner": _file_binding(sim_path),
            "base_navigation": _file_binding(base_path),
        },
        "markers": markers,
        "all_markers_match": all(markers.values()),
        "current_tick_full_body_target_available": True,
        "high_level_base_goal_available": True,
        "right_arm_waypoint_plan_available_at_move_start": True,
        "right_arm_planned_joint_count": 6,
        "future_0_9s_29_body_joint_window_available": False,
        "conclusion": (
            "Source A does not expose a current-tick 29-joint future trajectory. "
            "Its legs are reactive; base navigation provides a pose goal; only the "
            "six-joint right arm has move-local precomputed waypoints."
        ),
    }


def _block_delta(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    import numpy as np

    if previous.keys() != current.keys():
        raise ValueError("observation block keys changed across one transition")
    result = {}
    for name in previous:
        delta = np.asarray(current[name], dtype=np.float64).reshape(-1) - np.asarray(
            previous[name], dtype=np.float64
        ).reshape(-1)
        result[name] = {
            "l_inf": float(np.max(np.abs(delta))),
            "l2": float(np.linalg.norm(delta)),
            "nonzero": int(np.count_nonzero(delta)),
        }
    return result


def _target_delta_row(
    previous: Any,
    current: Any,
    source_previous: Any,
    source_current: Any,
) -> dict[str, Any]:
    import numpy as np

    candidate_delta = np.asarray(current) - np.asarray(previous)
    source_delta = np.asarray(source_current) - np.asarray(source_previous)
    joint = int(np.argmax(np.abs(candidate_delta)))
    return {
        "candidate_max_joint_index": joint,
        "candidate_max_joint_name": SONIC_BODY_JOINT_ORDER[joint],
        "candidate_max_signed_delta_rad": float(candidate_delta[joint]),
        "candidate_max_abs_delta_rad": float(abs(candidate_delta[joint])),
        "source_delta_same_joint_rad": float(source_delta[joint]),
        "source_global_max_abs_delta_rad": float(np.max(np.abs(source_delta))),
        "source_global_max_joint_name": SONIC_BODY_JOINT_ORDER[
            int(np.argmax(np.abs(source_delta)))
        ],
    }


def run_variant(
    *,
    spec: Mapping[str, Any],
    inputs: MappingInputs,
    encoder: Any,
    decoder: Any,
    sample_count: int,
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    import numpy as np

    if sample_count <= 1 or sample_count > inputs.sample_count:
        raise ValueError("diagnostic sample count is invalid")
    if spec["reference"] == "recorded_future_state_oracle":
        if sample_count - 1 + G1_LOOKAHEAD_TICKS >= inputs.sample_count:
            raise ValueError("oracle diagnostic lacks a complete future window")
        encoder_builder = build_g1_encoder_blocks
    elif spec["reference"] == "causal_hold":
        encoder_builder = build_causal_hold_encoder_blocks
    elif spec["reference"] == "causal_measured_state_hold":
        encoder_builder = build_causal_measured_state_hold_encoder_blocks
    elif spec["reference"] == "causal_damped_state_projection":
        encoder_builder = build_causal_damped_state_projection_encoder_blocks
    elif spec["reference"] == "causal_measured_state_mean10_hold":
        encoder_builder = build_causal_measured_state_mean10_hold_encoder_blocks
    else:
        raise ValueError(f"unknown reference variant: {spec['reference']}")

    autoregressive = spec["action_history"] == "autoregressive"
    source_applied_history = (
        spec["action_history"] == "source_a_applied_one_step_takeover"
    )
    if (
        not autoregressive
        and not source_applied_history
        and spec["action_history"] != "all_zero_ablation"
    ):
        raise ValueError(f"unknown action-history variant: {spec['action_history']}")
    if source_applied_history:
        logged_actions = build_source_applied_action_history(inputs, sample_count)
    else:
        logged_actions = np.zeros((sample_count, 29), dtype=np.float64)
    prepared = prepare_decoder_state(inputs)
    raw_actions = np.zeros((sample_count, 29), dtype=np.float64)
    targets = np.zeros((sample_count, 29), dtype=np.float64)
    hashes = {
        name: hashlib.sha256()
        for name in (
            "encoder_inputs",
            "encoder_tokens",
            "decoder_inputs",
            "raw_actions",
            "targets",
        )
    }
    transition_rows: dict[str, Any] = {}
    previous_encoder_blocks: Mapping[str, Any] | None = None
    previous_decoder_blocks: Mapping[str, Any] | None = None
    previous_target: Any | None = None
    started = time.perf_counter()

    for index in range(sample_count):
        encoder_blocks = encoder_builder(inputs, index)
        encoder_input = np.asarray(
            [ENCODER_ASSEMBLER.assemble(encoder_blocks)], dtype=np.float32
        )
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_blocks = build_decoder_blocks(
            inputs,
            index,
            token_state=token,
            logged_last_actions_isaaclab=logged_actions,
            prepared_state=prepared,
        )
        decoder_input = np.asarray(
            [DECODER_ASSEMBLER.assemble(decoder_blocks)], dtype=np.float32
        )
        raw = decoder.run(None, {decoder.get_inputs()[0].name: decoder_input})[
            0
        ].reshape(-1)
        if not (
            np.isfinite(encoder_input).all()
            and np.isfinite(token).all()
            and np.isfinite(decoder_input).all()
            and np.isfinite(raw).all()
        ):
            raise RuntimeError(f"non-finite value in {spec['name']} at sample {index}")
        raw_actions[index] = raw
        if autoregressive and index + 1 < sample_count:
            logged_actions[index + 1] = raw
        phase = _phase_at(inputs.phase_events, float(inputs.times_s[index]))
        target = body_joint_target_from_raw_action(
            raw, phase=phase, sim_time_s=float(inputs.times_s[index])
        )
        targets[index] = target.position_target_rad

        if index in DIAGNOSTIC_TO_INDICES:
            if (
                previous_encoder_blocks is None
                or previous_decoder_blocks is None
                or previous_target is None
            ):
                raise RuntimeError("diagnostic transition has no previous sample")
            transition_rows[f"{index - 1}->{index}"] = {
                "from_sim_time_s": float(inputs.times_s[index - 1]),
                "to_sim_time_s": float(inputs.times_s[index]),
                "phase": phase,
                "target_delta": _target_delta_row(
                    previous_target,
                    targets[index],
                    inputs.source_targets_mujoco_rad[index - 1],
                    inputs.source_targets_mujoco_rad[index],
                ),
                "raw_action_delta_l_inf": float(
                    np.max(np.abs(raw_actions[index] - raw_actions[index - 1]))
                ),
                "encoder_block_delta": _block_delta(
                    previous_encoder_blocks, encoder_blocks
                ),
                "decoder_block_delta": _block_delta(
                    previous_decoder_blocks, decoder_blocks
                ),
                "encoder_token_delta": {
                    "l_inf": float(
                        np.max(
                            np.abs(
                                np.asarray(decoder_blocks["token_state"])
                                - np.asarray(previous_decoder_blocks["token_state"])
                            )
                        )
                    ),
                    "l2": float(
                        np.linalg.norm(
                            np.asarray(decoder_blocks["token_state"])
                            - np.asarray(previous_decoder_blocks["token_state"])
                        )
                    ),
                },
            }

        previous_encoder_blocks = {
            name: np.asarray(value).copy() for name, value in encoder_blocks.items()
        }
        previous_decoder_blocks = {
            name: np.asarray(value).copy() for name, value in decoder_blocks.items()
        }
        previous_target = targets[index].copy()
        _update_float32_hash(hashes["encoder_inputs"], encoder_input)
        _update_float32_hash(hashes["encoder_tokens"], token)
        _update_float32_hash(hashes["decoder_inputs"], decoder_input)
        _update_float32_hash(hashes["raw_actions"], raw)
        _update_float32_hash(hashes["targets"], targets[index])

    elapsed = time.perf_counter() - started
    result = {
        **dict(spec),
        "status": "executed_non_actuating_diagnostic",
        "sample_count": sample_count,
        "first_sim_time_s": float(inputs.times_s[0]),
        "last_sim_time_s": float(inputs.times_s[sample_count - 1]),
        "model_forwards": sample_count * 2,
        "physics_steps": 0,
        "elapsed_wall_s": elapsed,
        "mean_wall_ms_per_encoder_decoder_pair": elapsed * 1000.0 / sample_count,
        "all_outputs_finite": True,
        "stream_hashes_float32_concatenated": {
            name: hasher.hexdigest() for name, hasher in hashes.items()
        },
        "target_non_regression_gate": evaluate_non_regression_gate(targets, gate),
        "diagnostic_transitions": transition_rows,
        "actuation_enabled": False,
        "candidate_consumed_by_physics": False,
    }
    if source_applied_history:
        result["one_step_takeover_screen"] = evaluate_one_step_takeover_screen(
            targets,
            inputs.source_targets_mujoco_rad[:sample_count],
            inputs.times_s[:sample_count],
            gate,
        )
    return result


def run_diagnostic(
    *,
    s3_episode: Path,
    sonic_root: Path,
    source_a_root: Path,
    output_path: Path | None = None,
    observed_at: str | None = None,
    audit_only: bool = False,
    sample_count: int = DEFAULT_SAMPLE_COUNT,
) -> dict[str, Any]:
    import onnxruntime as ort

    s3_episode = s3_episode.resolve()
    sonic_root = sonic_root.resolve()
    source_a_root = source_a_root.resolve()
    output_path = output_path or sonic_root / "SONIC_CAUSAL_REFERENCE_DIAGNOSTIC.json"
    inputs, bindings = load_mapping_inputs(
        s3_episode=s3_episode, source_a_root=source_a_root
    )
    source_capability = inspect_source_a_reference_capability(source_a_root)
    gate = build_source_non_regression_gate(inputs, source_a_root)
    encoder_path = sonic_root / "weights/sonic_v1_1/model_encoder.onnx"
    decoder_path = sonic_root / "weights/sonic_v1_1/model_decoder.onnx"
    variants = []
    if not audit_only:
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
        variants = [
            run_variant(
                spec=spec,
                inputs=inputs,
                encoder=encoder,
                decoder=decoder,
                sample_count=sample_count,
                gate=gate,
            )
            for spec in VARIANTS
        ]

    baseline = next(
        (row for row in variants if row["name"] == "causal_hold_autoregressive"),
        None,
    )
    zero_history = next(
        (row for row in variants if row["name"] == "causal_hold_zero_action_history"),
        None,
    )
    oracle = next(
        (
            row
            for row in variants
            if row["name"] == "future_state_oracle_autoregressive"
        ),
        None,
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "implementation": _file_binding(Path(__file__)),
        "inputs": {
            "s3_episode": str(s3_episode),
            "sonic_root": str(sonic_root),
            "source_a_root": str(source_a_root),
            "bindings": bindings,
            "encoder_model": _file_binding(encoder_path),
            "decoder_model": _file_binding(decoder_path),
        },
        "source_a_reference_capability": source_capability,
        "frozen_non_regression_gate": gate,
        "diagnostic_contract": {
            "sample_count": sample_count,
            "diagnostic_to_indices": list(DIAGNOSTIC_TO_INDICES),
            "variants": [dict(row) for row in VARIANTS],
            "all_variants_non_actuating": True,
            "zero_history_is_deployable": False,
            "future_oracle_is_causal": False,
        },
        "variants": variants,
        "interpretation_inputs": {
            "baseline_gate_passed": (
                None
                if baseline is None
                else baseline["target_non_regression_gate"]["passed"]
            ),
            "zero_history_gate_passed": (
                None
                if zero_history is None
                else zero_history["target_non_regression_gate"]["passed"]
            ),
            "future_oracle_gate_passed": (
                None
                if oracle is None
                else oracle["target_non_regression_gate"]["passed"]
            ),
        },
        "gates": {
            "source_a_capability_audited": source_capability["all_markers_match"],
            "source_a_future_0_9s_29_joint_reference_available": False,
            "non_regression_gate_frozen_before_candidate_comparison": True,
            "bounded_ablation_executed": bool(variants),
            "full_stream_causal_candidate_ready": False,
            "current_tick_runtime_integration_ready": False,
            "physics_smoke_admission_ready": False,
            "actuation_enabled": False,
            "candidate_consumed_by_physics": False,
            "production_accepted": False,
            "learning_validated": False,
            "long_run_authorized": True,
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "model_forwards": sum(int(row["model_forwards"]) for row in variants),
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "claim_boundary": (
            "This bounded diagnostic attributes discontinuities on frozen states. "
            "The zero-history branch changes official decoder semantics and the future "
            "oracle reads recorded future rows; neither is a controller candidate. No "
            "variant is admitted to physics by this report."
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
    parser.add_argument("--sample-count", type=int, default=DEFAULT_SAMPLE_COUNT)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_diagnostic(
        s3_episode=args.s3_episode,
        sonic_root=args.sonic_root,
        source_a_root=args.source_a_root,
        output_path=args.output,
        observed_at=args.observed_at,
        audit_only=args.audit_only,
        sample_count=args.sample_count,
    )
    print(
        json.dumps(
            {
                "output": str(
                    args.output
                    or args.sonic_root / "SONIC_CAUSAL_REFERENCE_DIAGNOSTIC.json"
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
