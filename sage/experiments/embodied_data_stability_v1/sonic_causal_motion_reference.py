"""Build and screen a task-conditioned causal SONIC motion reference.

The reference never reads a state row after the current control tick.  Once a
task/action segment contains enough history, it finds the ten closest earlier
states whose complete 0.9 s continuation is already in the past.  Those past
continuations are averaged, aligned to the current measured pose, and blended
with the previous rolling forecast.  Before such history exists, the builder
fails closed to a measured-state hold.

This is an expert-conditioned online motion prior, not an independent task
planner: current phase, high-level action identity, measured state, and the
current Source-A body target all participate in the match.  Recorded future
rows are used only after construction to score prediction error.  This module
does not advance physics and has no actuator write path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import resource
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_causal_hold_shadow import _prefix
from .sonic_causal_reference_diagnostic import (
    build_source_applied_action_history,
    build_source_non_regression_gate,
    evaluate_non_regression_gate,
    evaluate_one_step_takeover_screen,
)
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
    _verified_npz,
    build_decoder_blocks,
    load_mapping_inputs,
    prepare_decoder_state,
    reorder_mujoco_to_isaaclab,
)
from .sonic_causal_reference_diagnostic import TAKEOVER_QUALIFICATION_TICKS
from .sonic_causal_reference_diagnostic import NUMERIC_TOLERANCE_RAD
from .sonic_causal_reference_diagnostic import _true_runs
from .sonic_causal_reference_diagnostic import inspect_source_a_reference_capability
from .sonic_causal_hold_shadow import build_causal_hold_encoder_blocks
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import SONIC_BODY_JOINT_ORDER


SCHEMA = "sonic-causal-motion-reference-shadow/v1"
REFERENCE_SEMANTICS = "past_only_same_task_segment_analog_trajectory"
CONTEXT_TICKS = 10
NEIGHBOR_COUNT = 10
REFERENCE_BLEND = 0.05
VELOCITY_DISTANCE_WEIGHT = 0.0064
TREND_DISTANCE_WEIGHT = 1.0
SOURCE_TARGET_DISTANCE_WEIGHT = 1.0
FRAME_OFFSETS = tuple(
    index * G1_FUTURE_STEP for index in range(G1_FUTURE_FRAMES)
)
LOCOMOTION_PHASES = ("approach", "carry", "retreat")
ACTIVE_JOINT_RMS_VELOCITY_RAD_S = 0.05
MOTION_REFERENCE_MIN_DISPLACEMENT_RAD = 0.02
PREFIX_PROBE_CANDIDATES = (0, 1, 44, 45, 54, 55, 56, 230, 1000)
DEFAULT_OUTPUT = DEFAULT_SONIC_RUN / "SONIC_CAUSAL_MOTION_REFERENCE_SHADOW.json"


@dataclass(frozen=True)
class CausalReferenceStream:
    positions_mujoco_rad: Any
    velocities_mujoco_rad_s: Any
    next_tick_position_mujoco_rad: Any
    analog_available: Any
    match_score: Any
    neighbor_indices: Any
    maximum_consumed_state_index: Any
    phases: tuple[str, ...]
    high_level_action_indices: Any

    @property
    def sample_count(self) -> int:
        return int(self.positions_mujoco_rad.shape[0])


@dataclass(frozen=True)
class CausalReferenceTick:
    positions_mujoco_rad: Any
    velocities_mujoco_rad_s: Any
    next_tick_position_mujoco_rad: Any
    analog_available: bool
    match_score: float
    neighbor_indices: tuple[int, ...]
    maximum_consumed_state_index: int
    phase: str
    high_level_action_index: int
    maximum_future_displacement_rad: float


class OnlineCausalReferenceBuilder:
    """Incremental form of the frozen causal-reference algorithm."""

    def __init__(self) -> None:
        self.positions: list[Any] = []
        self.velocities: list[Any] = []
        self.source_targets: list[Any] = []
        self.phases: list[str] = []
        self.action_indices: list[int] = []
        self.segment_start = 0
        self.previous_positions: Any | None = None
        self.previous_velocities: Any | None = None

    def append(
        self,
        *,
        position_mujoco_rad: Any,
        velocity_mujoco_rad_s: Any,
        source_target_mujoco_rad: Any,
        phase: str,
        high_level_action_index: int,
    ) -> CausalReferenceTick:
        import numpy as np

        position = np.asarray(position_mujoco_rad, dtype=np.float64)
        velocity = np.asarray(velocity_mujoco_rad_s, dtype=np.float64)
        source_target = np.asarray(source_target_mujoco_rad, dtype=np.float64)
        if any(value.shape != (29,) for value in (position, velocity, source_target)):
            raise ValueError("online causal reference inputs must be 29-vectors")
        if not all(
            np.isfinite(value).all() for value in (position, velocity, source_target)
        ):
            raise ValueError("online causal reference inputs must be finite")
        if not phase.strip():
            raise ValueError("online causal reference phase must be non-empty")

        index = len(self.positions)
        action_index = int(high_level_action_index)
        if index and (
            phase != self.phases[-1] or action_index != self.action_indices[-1]
        ):
            self.segment_start = index
        self.positions.append(position.copy())
        self.velocities.append(velocity.copy())
        self.source_targets.append(source_target.copy())
        self.phases.append(phase)
        self.action_indices.append(action_index)

        positions = np.asarray(self.positions, dtype=np.float64)
        velocities = np.asarray(self.velocities, dtype=np.float64)
        source_targets = np.asarray(self.source_targets, dtype=np.float64)
        fresh_positions = np.repeat(
            position[None, :], G1_LOOKAHEAD_TICKS + 1, axis=0
        )
        fresh_velocities = np.zeros_like(fresh_positions)
        analog_available = False
        match_score = float("nan")
        selected = np.empty(0, dtype=np.int64)
        maximum_consumed = index
        lo = self.segment_start + CONTEXT_TICKS
        hi = index - G1_LOOKAHEAD_TICKS
        if hi >= lo and index >= CONTEXT_TICKS:
            candidates = np.arange(lo, hi + 1, dtype=np.int64)
            same_segment = np.asarray(
                [
                    self.phases[candidate + G1_LOOKAHEAD_TICKS] == phase
                    and self.action_indices[candidate + G1_LOOKAHEAD_TICKS]
                    == action_index
                    for candidate in candidates
                ],
                dtype=bool,
            )
            candidates = candidates[same_segment]
            if candidates.size:
                position_distance = np.mean(
                    np.square(positions[candidates] - position), axis=1
                )
                velocity_distance = np.mean(
                    np.square(velocities[candidates] - velocity), axis=1
                )
                current_trend = position - positions[index - CONTEXT_TICKS]
                candidate_trend = (
                    positions[candidates] - positions[candidates - CONTEXT_TICKS]
                )
                trend_distance = np.mean(
                    np.square(candidate_trend - current_trend), axis=1
                )
                target_distance = np.mean(
                    np.square(source_targets[candidates] - source_target), axis=1
                )
                distance = (
                    position_distance
                    + VELOCITY_DISTANCE_WEIGHT * velocity_distance
                    + TREND_DISTANCE_WEIGHT * trend_distance
                    + SOURCE_TARGET_DISTANCE_WEIGHT * target_distance
                )
                count = min(NEIGHBOR_COUNT, candidates.size)
                selected_offsets = np.argpartition(distance, count - 1)[:count]
                selected = candidates[selected_offsets]
                histories_position = np.stack(
                    [
                        positions[
                            candidate : candidate + G1_LOOKAHEAD_TICKS + 1
                        ]
                        for candidate in selected
                    ]
                )
                histories_velocity = np.stack(
                    [
                        velocities[
                            candidate : candidate + G1_LOOKAHEAD_TICKS + 1
                        ]
                        for candidate in selected
                    ]
                )
                fresh_positions = histories_position.mean(axis=0)
                fresh_positions += position - positions[selected].mean(axis=0)
                fresh_positions[0] = position
                fresh_velocities = histories_velocity.mean(axis=0)
                fresh_velocities[0] = velocity
                analog_available = True
                match_score = float(distance[selected_offsets].mean())
                maximum_consumed = int(selected.max() + G1_LOOKAHEAD_TICKS)

        same_segment_as_previous = bool(
            index
            and phase == self.phases[index - 1]
            and action_index == self.action_indices[index - 1]
        )
        if (
            analog_available
            and same_segment_as_previous
            and self.previous_positions is not None
            and self.previous_velocities is not None
        ):
            shifted_positions = np.concatenate(
                [self.previous_positions[1:], self.previous_positions[-1:]], axis=0
            )
            shifted_positions += position - shifted_positions[0]
            shifted_velocities = np.concatenate(
                [self.previous_velocities[1:], self.previous_velocities[-1:]],
                axis=0,
            )
            output_positions = (
                (1.0 - REFERENCE_BLEND) * shifted_positions
                + REFERENCE_BLEND * fresh_positions
            )
            output_velocities = (
                (1.0 - REFERENCE_BLEND) * shifted_velocities
                + REFERENCE_BLEND * fresh_velocities
            )
            output_positions[0] = position
            output_velocities[0] = velocity
        else:
            output_positions = fresh_positions
            output_velocities = fresh_velocities

        if maximum_consumed > index:
            raise RuntimeError("online causal reference consumed a future state row")
        self.previous_positions = output_positions
        self.previous_velocities = output_velocities
        frames = np.asarray(FRAME_OFFSETS, dtype=np.int64)
        frame_positions = output_positions[frames]
        frame_velocities = output_velocities[frames]
        return CausalReferenceTick(
            positions_mujoco_rad=frame_positions,
            velocities_mujoco_rad_s=frame_velocities,
            next_tick_position_mujoco_rad=output_positions[1].copy(),
            analog_available=analog_available,
            match_score=match_score,
            neighbor_indices=tuple(int(value) for value in selected),
            maximum_consumed_state_index=maximum_consumed,
            phase=phase,
            high_level_action_index=action_index,
            maximum_future_displacement_rad=float(
                np.max(np.abs(frame_positions - frame_positions[:1]))
            ),
        )


def load_task_conditioning(
    s3_episode: Path, sample_count: int
) -> tuple[Any, list[dict[str, Any]], dict[str, Any]]:
    """Load the current-tick action identity and its bound high-level goals."""

    import numpy as np

    policy, policy_binding = _verified_npz(s3_episode / "state_stream", "policy")
    if "previous_high_level_action_index" not in policy:
        raise ValueError("policy stream lacks previous_high_level_action_index")
    action_indices = np.asarray(
        policy["previous_high_level_action_index"], dtype=np.int64
    ).reshape(-1)
    if action_indices.shape != (sample_count,):
        raise ValueError("high-level action index count differs from state stream")

    decision_path = s3_episode / "episode_contract" / "policy.jsonl"
    decisions = []
    for line in decision_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        decision = int(row["decision_index"])
        goal = row["action"].get("base_pose_xyyaw")
        decisions.append(
            {
                "decision_index": decision,
                "issued_at_s": float(row["action"]["issued_at_s"]),
                "phase": str(row["phase"]),
                "base_pose_xyyaw": None
                if goal is None
                else [float(value) for value in goal],
                "task_type": str(row["instruction"]["task_type"]),
            }
        )
    expected = sorted(int(value) for value in np.unique(action_indices) if value >= 0)
    observed = sorted(row["decision_index"] for row in decisions)
    if expected != observed:
        raise ValueError("policy decisions do not cover recorded action identities")
    return action_indices, decisions, {
        "policy_state": policy_binding["file"],
        "policy_decisions": _file_binding(decision_path),
    }


def _validated_action_indices(values: Any, rows: int) -> Any:
    import numpy as np

    result = np.asarray(values, dtype=np.int64).reshape(-1)
    if result.shape != (rows,):
        raise ValueError("high-level action indices must have one value per state")
    return result


def build_causal_reference_stream(
    inputs: MappingInputs, high_level_action_indices: Any
) -> CausalReferenceStream:
    """Construct all rolling forecasts using only rows at or before each tick."""

    import numpy as np

    rows = inputs.sample_count
    action_indices = _validated_action_indices(high_level_action_indices, rows)
    positions = np.asarray(inputs.body_position_mujoco_rad, dtype=np.float64)
    velocities = np.asarray(inputs.body_velocity_mujoco_rad_s, dtype=np.float64)
    source_targets = np.asarray(inputs.source_targets_mujoco_rad, dtype=np.float64)
    if positions.shape != (rows, 29) or velocities.shape != (rows, 29):
        raise ValueError("causal reference requires [N,29] measured body state")
    if source_targets.shape != (rows, 29):
        raise ValueError("causal reference requires [N,29] Source-A targets")
    if not (
        np.isfinite(positions).all()
        and np.isfinite(velocities).all()
        and np.isfinite(source_targets).all()
    ):
        raise ValueError("causal reference inputs must be finite")

    phases = tuple(
        _phase_at(inputs.phase_events, float(value)) for value in inputs.times_s
    )
    frame_positions = np.empty(
        (rows, G1_FUTURE_FRAMES, 29), dtype=np.float64
    )
    frame_velocities = np.empty_like(frame_positions)
    next_tick = np.empty((rows, 29), dtype=np.float64)
    available = np.zeros(rows, dtype=bool)
    match_score = np.full(rows, np.nan, dtype=np.float64)
    neighbors = np.full((rows, NEIGHBOR_COUNT), -1, dtype=np.int64)
    max_consumed = np.arange(rows, dtype=np.int64)
    builder = OnlineCausalReferenceBuilder()
    for index in range(rows):
        tick = builder.append(
            position_mujoco_rad=positions[index],
            velocity_mujoco_rad_s=velocities[index],
            source_target_mujoco_rad=source_targets[index],
            phase=phases[index],
            high_level_action_index=int(action_indices[index]),
        )
        frame_positions[index] = tick.positions_mujoco_rad
        frame_velocities[index] = tick.velocities_mujoco_rad_s
        next_tick[index] = tick.next_tick_position_mujoco_rad
        available[index] = tick.analog_available
        match_score[index] = tick.match_score
        neighbors[index, : len(tick.neighbor_indices)] = tick.neighbor_indices
        max_consumed[index] = tick.maximum_consumed_state_index

    return CausalReferenceStream(
        positions_mujoco_rad=frame_positions,
        velocities_mujoco_rad_s=frame_velocities,
        next_tick_position_mujoco_rad=next_tick,
        analog_available=available,
        match_score=match_score,
        neighbor_indices=neighbors,
        maximum_consumed_state_index=max_consumed,
        phases=phases,
        high_level_action_indices=action_indices,
    )


def build_motion_encoder_blocks(
    inputs: MappingInputs, reference: CausalReferenceStream, index: int
) -> dict[str, Any]:
    """Assemble official g1 blocks from one already-causal rolling forecast."""

    import numpy as np

    if index < 0 or index >= inputs.sample_count or index >= reference.sample_count:
        raise ValueError("causal motion reference index is invalid")
    blocks = build_causal_hold_encoder_blocks(inputs, index)
    positions = reorder_mujoco_to_isaaclab(
        reference.positions_mujoco_rad[index]
    )
    velocities = reorder_mujoco_to_isaaclab(
        reference.velocities_mujoco_rad_s[index]
    )
    blocks["motion_joint_positions_10frame_step5"] = np.asarray(
        positions, dtype=np.float64
    ).reshape(-1)
    blocks["motion_joint_velocities_10frame_step5"] = np.asarray(
        velocities, dtype=np.float64
    ).reshape(-1)
    return blocks


def _error_metrics(
    prediction: Any,
    actual: Any,
    mask: Any,
    *,
    times_s: Any,
    horizon_offsets: Sequence[int],
) -> dict[str, Any]:
    import numpy as np

    predicted = np.asarray(prediction, dtype=np.float64)
    observed = np.asarray(actual, dtype=np.float64)
    enabled = np.asarray(mask, dtype=bool)
    if predicted.shape != observed.shape or predicted.ndim != 3:
        raise ValueError("prediction metric arrays must have the same [N,H,29] shape")
    if enabled.shape != (predicted.shape[0],) or not enabled.any():
        raise ValueError("prediction metric mask is empty or has the wrong shape")
    error = predicted[enabled] - observed[enabled]
    absolute = np.abs(error)
    flat_worst = int(np.argmax(absolute))
    selected_row, horizon, joint = np.unravel_index(flat_worst, absolute.shape)
    original_rows = np.flatnonzero(enabled)
    row = int(original_rows[selected_row])
    return {
        "sample_count": int(enabled.sum()),
        "value_count": int(absolute.size),
        "mean_absolute_error_rad": float(absolute.mean()),
        "rms_error_rad": float(math.sqrt(float(np.square(error).mean()))),
        "p95_absolute_error_rad": float(np.percentile(absolute, 95.0)),
        "global_max_absolute_error_rad": float(absolute.reshape(-1)[flat_worst]),
        "worst": {
            "sample_index": row,
            "sim_time_s": float(np.asarray(times_s)[row]),
            "horizon_ticks": int(horizon_offsets[horizon]),
            "horizon_s": float(horizon_offsets[horizon] * CONTROL_DT_S),
            "joint_index": int(joint),
            "joint_name": SONIC_BODY_JOINT_ORDER[joint],
            "signed_error_rad": float(error[selected_row, horizon, joint]),
        },
    }


def evaluate_reference_prediction(
    inputs: MappingInputs, reference: CausalReferenceStream
) -> dict[str, Any]:
    """Score the frozen future only after the causal references are complete."""

    import numpy as np

    valid_rows = inputs.sample_count - G1_LOOKAHEAD_TICKS
    if valid_rows <= 0:
        raise ValueError("prediction evaluation needs a complete 0.9 s future")
    indices = np.arange(valid_rows)
    future_offsets = FRAME_OFFSETS[1:]
    actual = np.stack(
        [inputs.body_position_mujoco_rad[indices + offset] for offset in future_offsets],
        axis=1,
    )
    candidate = np.asarray(reference.positions_mujoco_rad[:valid_rows, 1:])
    hold = np.repeat(
        np.asarray(inputs.body_position_mujoco_rad[:valid_rows])[:, None, :],
        len(future_offsets),
        axis=1,
    )
    phase_array = np.asarray(reference.phases[:valid_rows])
    velocity_rms = np.sqrt(
        np.mean(
            np.square(inputs.body_velocity_mujoco_rad_s[:valid_rows]), axis=1
        )
    )
    masks = {
        "all": np.ones(valid_rows, dtype=bool),
        "locomotion_task_phases": np.isin(phase_array, LOCOMOTION_PHASES),
        "causally_active_joint_state": (
            velocity_rms >= ACTIVE_JOINT_RMS_VELOCITY_RAD_S
        ),
    }
    scopes: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    for name, mask in masks.items():
        candidate_metrics = _error_metrics(
            candidate,
            actual,
            mask,
            times_s=inputs.times_s,
            horizon_offsets=future_offsets,
        )
        hold_metrics = _error_metrics(
            hold,
            actual,
            mask,
            times_s=inputs.times_s,
            horizon_offsets=future_offsets,
        )
        comparisons = {
            key: candidate_metrics[key] <= hold_metrics[key]
            for key in (
                "mean_absolute_error_rad",
                "rms_error_rad",
                "p95_absolute_error_rad",
                "global_max_absolute_error_rad",
            )
        }
        scopes[name] = {
            "candidate": candidate_metrics,
            "measured_state_hold_baseline": hold_metrics,
            "candidate_not_worse": comparisons,
        }
        checks[f"{name}_all_four_metrics_not_worse"] = all(comparisons.values())

    next_actual = np.asarray(inputs.body_position_mujoco_rad[1:])[:, None, :]
    next_candidate = np.asarray(reference.next_tick_position_mujoco_rad[:-1])[
        :, None, :
    ]
    next_hold = np.asarray(inputs.body_position_mujoco_rad[:-1])[:, None, :]
    next_mask = np.ones(inputs.sample_count - 1, dtype=bool)
    one_tick = {
        "candidate": _error_metrics(
            next_candidate,
            next_actual,
            next_mask,
            times_s=inputs.times_s,
            horizon_offsets=(1,),
        ),
        "measured_state_hold_baseline": _error_metrics(
            next_hold,
            next_actual,
            next_mask,
            times_s=inputs.times_s,
            horizon_offsets=(1,),
        ),
    }
    return {
        "evaluation_uses_future_only_after_reference_construction": True,
        "reference_horizon_offsets_ticks": list(FRAME_OFFSETS),
        "reference_horizon_s": G1_LOOKAHEAD_TICKS * CONTROL_DT_S,
        "scopes": scopes,
        "one_control_tick_0_02s": one_tick,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _stream_continuity(values: Any) -> dict[str, Any]:
    import numpy as np

    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 3 or array.shape[2] != 29 or array.shape[0] < 2:
        raise ValueError("reference continuity needs [N,H,29] values")
    delta = np.diff(array, axis=0)
    absolute = np.abs(delta)
    sample, horizon, joint = np.unravel_index(int(np.argmax(absolute)), absolute.shape)
    return {
        "mean_absolute_delta": float(absolute.mean()),
        "p99_9_absolute_delta": float(np.percentile(absolute, 99.9)),
        "global_max_absolute_delta": float(absolute[sample, horizon, joint]),
        "worst": {
            "from_sample_index": int(sample),
            "to_sample_index": int(sample + 1),
            "horizon_ticks": int(FRAME_OFFSETS[horizon]),
            "joint_index": int(joint),
            "joint_name": SONIC_BODY_JOINT_ORDER[joint],
            "signed_delta": float(delta[sample, horizon, joint]),
        },
    }


def evaluate_reference_integrity(
    reference: CausalReferenceStream, gate: Mapping[str, Any]
) -> dict[str, Any]:
    import numpy as np

    positions = np.asarray(reference.positions_mujoco_rad, dtype=np.float64)
    velocities = np.asarray(reference.velocities_mujoco_rad_s, dtype=np.float64)
    envelope = gate["allowed_command_envelope"]
    lower = np.asarray(envelope["admission_lower_rad"], dtype=np.float64)
    upper = np.asarray(envelope["admission_upper_rad"], dtype=np.float64)
    violations = (positions < lower[None, None, :] - NUMERIC_TOLERANCE_RAD) | (
        positions > upper[None, None, :] + NUMERIC_TOLERANCE_RAD
    )
    max_consumed = np.asarray(reference.maximum_consumed_state_index)
    causal = max_consumed <= np.arange(reference.sample_count)
    position_continuity = _stream_continuity(positions)
    source_limit = float(gate["allowed_global_max_abs_delta_rad"])
    checks = {
        "all_reference_values_finite": bool(
            np.isfinite(positions).all() and np.isfinite(velocities).all()
        ),
        "no_state_row_after_current_tick_consumed": bool(causal.all()),
        "all_reference_positions_inside_model_or_source_envelope": not bool(
            violations.any()
        ),
        "reference_update_max_not_worse_than_source_command_limit": (
            position_continuity["global_max_absolute_delta"] <= source_limit
        ),
    }
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "analog_available_samples": int(np.asarray(reference.analog_available).sum()),
        "hold_fallback_samples": int((~np.asarray(reference.analog_available)).sum()),
        "maximum_consumed_minus_current_offset": int(
            np.max(max_consumed - np.arange(reference.sample_count))
        ),
        "position_continuity_50hz_reference_updates": position_continuity,
        "velocity_continuity_50hz_reference_updates": _stream_continuity(velocities),
        "source_command_continuity_limit_rad": source_limit,
        "reference_position_envelope_violation_count": int(violations.sum()),
        "no_output_clipping_or_rate_limiting": True,
    }


def _truncated_prefix(inputs: MappingInputs, end_exclusive: int) -> MappingInputs:
    result = _prefix(inputs, end_exclusive)
    last_time = float(result.times_s[-1])
    return replace(
        result,
        phase_events=tuple(
            row
            for row in inputs.phase_events
            if float(row["sim_time_s"]) <= last_time
        ),
    )


def verify_prefix_equivalence(
    inputs: MappingInputs,
    high_level_action_indices: Any,
    full_reference: CausalReferenceStream,
) -> dict[str, Any]:
    """Compare full-stream observations to physically truncated state prefixes."""

    import numpy as np

    indices = sorted(
        {
            *(
                value
                for value in PREFIX_PROBE_CANDIDATES
                if 0 <= value < inputs.sample_count
            ),
            inputs.sample_count - 1,
        }
    )
    action_indices = _validated_action_indices(
        high_level_action_indices, inputs.sample_count
    )
    rows = []
    for index in indices:
        prefix_inputs = _truncated_prefix(inputs, index + 1)
        prefix_reference = build_causal_reference_stream(
            prefix_inputs, action_indices[: index + 1]
        )
        full_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(
                build_motion_encoder_blocks(inputs, full_reference, index)
            ),
            dtype=np.float32,
        )
        prefix_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(
                build_motion_encoder_blocks(prefix_inputs, prefix_reference, index)
            ),
            dtype=np.float32,
        )
        equal = bool(np.array_equal(full_encoder, prefix_encoder))
        rows.append(
            {
                "sample_index": index,
                "prefix_sample_count": index + 1,
                "analog_available": bool(full_reference.analog_available[index]),
                "maximum_consumed_state_index": int(
                    full_reference.maximum_consumed_state_index[index]
                ),
                "encoder_equal": equal,
                "encoder_sha256": hashlib.sha256(full_encoder.tobytes()).hexdigest(),
            }
        )
    return {
        "method": "full_stream_vs_physically_truncated_prefix_exact_float32_equality",
        "probe_count": len(rows),
        "maximum_future_row_offset": 0,
        "all_equal": all(row["encoder_equal"] for row in rows),
        "probes": rows,
    }


def evaluate_motion_takeover_screen(
    *,
    targets: Any,
    inputs: MappingInputs,
    reference: CausalReferenceStream,
    gate: Mapping[str, Any],
    qualification_ticks: int = TAKEOVER_QUALIFICATION_TICKS,
) -> dict[str, Any]:
    """Require a guarded takeover window whose reference actually moves."""

    import numpy as np

    values = np.asarray(targets, dtype=np.float64)
    source = np.asarray(inputs.source_targets_mujoco_rad, dtype=np.float64)
    if values.shape != (inputs.sample_count, 29) or source.shape != values.shape:
        raise ValueError("motion takeover targets have inconsistent shapes")
    previous_command = np.vstack([source[0], source[:-1]])
    handoff_ok = np.max(np.abs(values - previous_command), axis=1) <= float(
        gate["allowed_global_max_abs_delta_rad"]
    )
    envelope = gate["allowed_command_envelope"]
    lower = np.asarray(envelope["admission_lower_rad"], dtype=np.float64)
    upper = np.asarray(envelope["admission_upper_rad"], dtype=np.float64)
    envelope_ok = (
        (values >= lower[None, :] - NUMERIC_TOLERANCE_RAD)
        & (values <= upper[None, :] + NUMERIC_TOLERANCE_RAD)
    ).all(axis=1)
    reference_displacement = np.max(
        np.abs(
            np.asarray(reference.positions_mujoco_rad)
            - np.asarray(reference.positions_mujoco_rad)[:, :1, :]
        ),
        axis=(1, 2),
    )
    motion_bearing = (
        np.asarray(reference.analog_available, dtype=bool)
        & np.isin(np.asarray(reference.phases), LOCOMOTION_PHASES)
        & (reference_displacement >= MOTION_REFERENCE_MIN_DISPLACEMENT_RAD)
    )
    eligible = handoff_ok & envelope_ok & motion_bearing
    eligible[0] = False
    runs = _true_runs(eligible)
    qualifying = [
        row for row in runs if row[1] - row[0] + 1 >= qualification_ticks
    ]
    longest = max((end - start + 1 for start, end in runs), default=0)
    return {
        "semantics": (
            "The SONIC proposal passes the frozen runtime handoff checks while "
            "the causal analog reference is available and its 0.9 s joint window "
            "contains task-stage motion rather than a hold."
        ),
        "motion_reference_min_displacement_rad": (
            MOTION_REFERENCE_MIN_DISPLACEMENT_RAD
        ),
        "locomotion_task_phases": list(LOCOMOTION_PHASES),
        "qualification_ticks": qualification_ticks,
        "qualification_duration_s": qualification_ticks * CONTROL_DT_S,
        "motion_bearing_sample_count": int(motion_bearing.sum()),
        "eligible_motion_sample_count": int(eligible.sum()),
        "longest_eligible_motion_run_ticks": longest,
        "longest_eligible_motion_run_s": longest * CONTROL_DT_S,
        "qualifying_motion_window_count": len(qualifying),
        "first_20_qualifying_motion_windows": [
            {
                "start_sample_index": start,
                "end_sample_index": end,
                "tick_count": end - start + 1,
                "start_sim_time_s": float(inputs.times_s[start]),
                "end_sim_time_s": float(inputs.times_s[end]),
                "phase": reference.phases[start],
                "maximum_reference_displacement_rad": float(
                    reference_displacement[start : end + 1].max()
                ),
            }
            for start, end in qualifying[:20]
        ],
        "passed": bool(qualifying),
    }


def run_sonic_shadow(
    *,
    inputs: MappingInputs,
    reference: CausalReferenceStream,
    encoder: Any,
    decoder: Any,
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    import numpy as np

    rows = inputs.sample_count
    logged_actions = build_source_applied_action_history(inputs, rows)
    prepared = prepare_decoder_state(inputs)
    targets = np.empty((rows, 29), dtype=np.float64)
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
    started = time.perf_counter()
    for index in range(rows):
        encoder_input = np.asarray(
            [
                ENCODER_ASSEMBLER.assemble(
                    build_motion_encoder_blocks(inputs, reference, index)
                )
            ],
            dtype=np.float32,
        )
        token = encoder.run(None, {encoder.get_inputs()[0].name: encoder_input})[0]
        decoder_input = np.asarray(
            [
                DECODER_ASSEMBLER.assemble(
                    build_decoder_blocks(
                        inputs,
                        index,
                        token_state=token,
                        logged_last_actions_isaaclab=logged_actions,
                        prepared_state=prepared,
                    )
                )
            ],
            dtype=np.float32,
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
            raise RuntimeError(f"non-finite SONIC value at sample {index}")
        target = body_joint_target_from_raw_action(
            raw,
            phase=reference.phases[index],
            sim_time_s=float(inputs.times_s[index]),
        )
        targets[index] = target.position_target_rad
        _update_float32_hash(hashes["encoder_inputs"], encoder_input)
        _update_float32_hash(hashes["encoder_tokens"], token)
        _update_float32_hash(hashes["decoder_inputs"], decoder_input)
        _update_float32_hash(hashes["raw_actions"], raw)
        _update_float32_hash(hashes["targets"], targets[index])
    elapsed = time.perf_counter() - started
    takeover = evaluate_one_step_takeover_screen(
        targets,
        inputs.source_targets_mujoco_rad,
        inputs.times_s,
        gate,
        qualification_ticks=TAKEOVER_QUALIFICATION_TICKS,
    )
    motion_takeover = evaluate_motion_takeover_screen(
        targets=targets,
        inputs=inputs,
        reference=reference,
        gate=gate,
    )
    return {
        "status": "executed_non_actuating_full_cpu_shadow",
        "sample_count": rows,
        "first_sim_time_s": float(inputs.times_s[0]),
        "last_sim_time_s": float(inputs.times_s[-1]),
        "model_forwards": rows * 2,
        "physics_steps": 0,
        "elapsed_wall_s": elapsed,
        "mean_wall_ms_per_encoder_decoder_pair": elapsed * 1000.0 / rows,
        "all_outputs_finite": True,
        "stream_hashes_float32_concatenated": {
            name: value.hexdigest() for name, value in hashes.items()
        },
        "target_non_regression_gate": evaluate_non_regression_gate(targets, gate),
        "one_step_takeover_screen": takeover,
        "motion_reference_takeover_screen": motion_takeover,
        "actuation_enabled": False,
        "candidate_consumed_by_physics": False,
    }


def run_full_motion_reference_shadow(
    *,
    s3_episode: Path = DEFAULT_S3_EPISODE,
    sonic_root: Path = DEFAULT_SONIC_RUN,
    source_a_root: Path = DEFAULT_SOURCE_A,
    output_path: Path = DEFAULT_OUTPUT,
    observed_at: str | None = None,
) -> dict[str, Any]:
    import onnxruntime as ort

    s3_episode = s3_episode.resolve()
    sonic_root = sonic_root.resolve()
    source_a_root = source_a_root.resolve()
    output_path = output_path.resolve()
    inputs, bindings = load_mapping_inputs(
        s3_episode=s3_episode, source_a_root=source_a_root
    )
    action_indices, decisions, conditioning_bindings = load_task_conditioning(
        s3_episode, inputs.sample_count
    )
    reference = build_causal_reference_stream(inputs, action_indices)
    gate = build_source_non_regression_gate(inputs, source_a_root)
    prediction = evaluate_reference_prediction(inputs, reference)
    integrity = evaluate_reference_integrity(reference, gate)
    prefix_proof = verify_prefix_equivalence(inputs, action_indices, reference)

    encoder_path = sonic_root / "weights/sonic_v1_1/model_encoder.onnx"
    decoder_path = sonic_root / "weights/sonic_v1_1/model_decoder.onnx"
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
    sonic = run_sonic_shadow(
        inputs=inputs,
        reference=reference,
        encoder=encoder,
        decoder=decoder,
        gate=gate,
    )
    takeover = sonic["one_step_takeover_screen"]
    motion_takeover = sonic["motion_reference_takeover_screen"]
    ready = bool(
        inputs.sample_count == 6209
        and prefix_proof["all_equal"]
        and prediction["passed"]
        and integrity["passed"]
        and sonic["all_outputs_finite"]
        and takeover["passed"]
        and motion_takeover["passed"]
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "implementation": _file_binding(Path(__file__)),
        "inputs": {
            "s3_episode": str(s3_episode),
            "sonic_root": str(sonic_root),
            "source_a_root": str(source_a_root),
            "bindings": {**bindings, **conditioning_bindings},
            "encoder_model": _file_binding(encoder_path),
            "decoder_model": _file_binding(decoder_path),
        },
        "task_conditioning": {
            "high_level_decisions": decisions,
            "current_tick_inputs": [
                "task phase",
                "previous high-level action identity bound to base_pose_xyyaw",
                "measured 29-joint position and velocity",
                "current Source-A 29-joint body target",
            ],
            "independent_task_planner": False,
            "source_a_dependency": (
                "The reference is conditioned on the current expert target and does "
                "not replace Source A as a task planner."
            ),
        },
        "reference_contract": {
            "semantics": REFERENCE_SEMANTICS,
            "control_rate_hz": int(round(1.0 / CONTROL_DT_S)),
            "future_frames": G1_FUTURE_FRAMES,
            "future_frame_step_ticks": G1_FUTURE_STEP,
            "future_offsets_ticks": list(FRAME_OFFSETS),
            "future_horizon_s": G1_LOOKAHEAD_TICKS * CONTROL_DT_S,
            "joint_count": 29,
            "joint_order": list(SONIC_BODY_JOINT_ORDER),
            "context_ticks": CONTEXT_TICKS,
            "neighbor_count": NEIGHBOR_COUNT,
            "rolling_fresh_forecast_blend": REFERENCE_BLEND,
            "hold_until_past_continuation_exists": True,
            "orientation_reference": "current measured base orientation held",
            "future_rows_available_to_builder": False,
            "output_clipping_or_rate_limiting": False,
        },
        "source_a_reference_capability": inspect_source_a_reference_capability(
            source_a_root
        ),
        "frozen_gate": gate,
        "causality_proof": prefix_proof,
        "reference_integrity": integrity,
        "prediction_evaluation": prediction,
        "sonic_cpu_shadow": sonic,
        "runtime_contract": {
            "implementation": _file_binding(
                Path(__file__).with_name("sonic_runtime_guard.py")
            ),
            "shadow_qualification_ticks": TAKEOVER_QUALIFICATION_TICKS,
            "maximum_active_ticks": 100,
            "maximum_active_duration_s": 100 * CONTROL_DT_S,
            "qualification_requires_motion_bearing_reference": True,
            "active_checks_repeat_every_tick": True,
            "output_clipping_or_rate_limiting": False,
            "dex3_commands_changed": False,
            "first_rejection": (
                "Never dispatch the failing SONIC proposal; use Source A only if "
                "its complete fallback command independently passes the same guard, "
                "then stop the bounded smoke."
            ),
        },
        "gates": {
            "full_6209_reference_stream_built": inputs.sample_count == 6209,
            "future_data_independence_verified": prefix_proof["all_equal"],
            "task_conditioned_0_9s_29_joint_reference_ready": bool(
                prefix_proof["all_equal"]
                and prediction["passed"]
                and integrity["passed"]
            ),
            "prediction_not_worse_than_hold_on_frozen_scopes": prediction[
                "passed"
            ],
            "reference_integrity_passed": integrity["passed"],
            "full_cpu_shadow_executed": sonic["sample_count"] == 6209,
            "all_sonic_outputs_finite": sonic["all_outputs_finite"],
            "one_step_takeover_window_available": takeover["passed"],
            "motion_bearing_takeover_window_available": motion_takeover[
                "passed"
            ],
            "runtime_guard_bound": True,
            "motion_physics_smoke_admission_ready": ready,
            "physics_executed": False,
            "actuation_enabled": False,
            "candidate_consumed_by_physics": False,
            "production_accepted": False,
            "task_success_validated": False,
            "learning_validated": False,
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "model_forwards": sonic["model_forwards"],
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "claim_boundary": (
            "This development-trajectory report proves current/past-only reference "
            "construction, frozen-trajectory prediction non-regression, and a CPU "
            "takeover screen. It does not prove closed-loop motion, independent task "
            "planning, grasp success, or production data quality."
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
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_full_motion_reference_shadow(
        s3_episode=args.s3_episode,
        sonic_root=args.sonic_root,
        source_a_root=args.source_a_root,
        output_path=args.output,
        observed_at=args.observed_at,
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
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
