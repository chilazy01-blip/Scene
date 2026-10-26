"""Audit whether SONIC has a guarded, causal base-translation window.

This is a zero-physics development-trajectory admission.  It reproduces the
full frozen SONIC target stream, requires the existing motion-reference and
handoff guards, and additionally requires the policy-visible horizontal base
speed to stay above a frozen threshold for the full qualification period.
Privileged base position is used only after selection to audit realized
displacement; it never participates in eligibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_causal_motion_reference import (
    LOCOMOTION_PHASES,
    MOTION_REFERENCE_MIN_DISPLACEMENT_RAD,
    CausalReferenceStream,
    build_causal_reference_stream,
    build_motion_encoder_blocks,
    load_task_conditioning,
)
from .sonic_causal_reference_diagnostic import (
    NUMERIC_TOLERANCE_RAD,
    TAKEOVER_QUALIFICATION_TICKS,
    _true_runs,
    build_source_applied_action_history,
    build_source_non_regression_gate,
)
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    DEFAULT_S3_EPISODE,
    DEFAULT_SONIC_RUN,
    DEFAULT_SOURCE_A,
    MappingInputs,
    _file_binding,
    _verified_npz,
    build_decoder_blocks,
    load_mapping_inputs,
    prepare_decoder_state,
)
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)


SCHEMA = "sonic-base-translation-admission/v1"
BASE_TRANSLATION_MIN_HORIZONTAL_SPEED_M_S = 0.05
SENSITIVITY_SPEED_THRESHOLDS_M_S = (0.02, 0.03, 0.05, 0.075, 0.1)
NON_TRANSLATION_CALIBRATION_PHASES = (
    "align",
    "grasp",
    "lift",
    "place",
    "release",
    "retreat",
)
DEFAULT_OUTPUT = DEFAULT_SONIC_RUN / "SONIC_BASE_TRANSLATION_ADMISSION.json"
CAUSAL_MOTION_REPORT = (
    DEFAULT_SONIC_RUN / "SONIC_CAUSAL_MOTION_REFERENCE_SHADOW.json"
)


def _validate_state_arrays(
    *,
    rows: int,
    base_velocity_m_s: Any,
    base_position_xy_m: Any,
) -> tuple[Any, Any]:
    import numpy as np

    velocity = np.asarray(base_velocity_m_s, dtype=np.float64)
    position = np.asarray(base_position_xy_m, dtype=np.float64)
    if velocity.shape != (rows, 6):
        raise ValueError(f"base velocity shape {velocity.shape} != {(rows, 6)}")
    if position.shape != (rows, 2):
        raise ValueError(f"base position shape {position.shape} != {(rows, 2)}")
    if not np.isfinite(velocity).all() or not np.isfinite(position).all():
        raise ValueError("base translation audit state must be finite")
    return velocity, position


def _window_record(
    *,
    start: int,
    end: int,
    inputs: MappingInputs,
    reference: CausalReferenceStream,
    horizontal_speed_m_s: Any,
    base_position_xy_m: Any,
    reference_displacement_rad: Any,
    handoff_delta_rad: Any,
) -> dict[str, Any]:
    import numpy as np

    xy = np.asarray(base_position_xy_m[start : end + 1], dtype=np.float64)
    step_distance = (
        np.linalg.norm(np.diff(xy, axis=0), axis=1)
        if xy.shape[0] > 1
        else np.empty(0, dtype=np.float64)
    )
    net = float(np.linalg.norm(xy[-1] - xy[0]))
    path = float(step_distance.sum())
    return {
        "start_sample_index": int(start),
        "end_sample_index": int(end),
        "tick_count": int(end - start + 1),
        "start_sim_time_s": float(inputs.times_s[start]),
        "end_sim_time_s": float(inputs.times_s[end]),
        "phases": sorted(set(reference.phases[start : end + 1])),
        "high_level_action_indices": sorted(
            set(
                int(value)
                for value in reference.high_level_action_indices[start : end + 1]
            )
        ),
        "minimum_horizontal_speed_m_s": float(
            np.min(horizontal_speed_m_s[start : end + 1])
        ),
        "maximum_horizontal_speed_m_s": float(
            np.max(horizontal_speed_m_s[start : end + 1])
        ),
        "mean_horizontal_speed_m_s": float(
            np.mean(horizontal_speed_m_s[start : end + 1])
        ),
        "actual_net_horizontal_displacement_m": net,
        "actual_horizontal_path_length_m": path,
        "net_to_path_ratio": 0.0 if path == 0.0 else net / path,
        "maximum_reference_displacement_rad": float(
            np.max(reference_displacement_rad[start : end + 1])
        ),
        "maximum_candidate_handoff_delta_rad": float(
            np.max(handoff_delta_rad[start : end + 1])
        ),
    }


def screen_base_translation_takeover(
    *,
    targets: Any,
    inputs: MappingInputs,
    reference: CausalReferenceStream,
    gate: Mapping[str, Any],
    base_velocity_m_s: Any,
    base_position_xy_m: Any,
    minimum_horizontal_speed_m_s: float = (
        BASE_TRANSLATION_MIN_HORIZONTAL_SPEED_M_S
    ),
    qualification_ticks: int = TAKEOVER_QUALIFICATION_TICKS,
    sensitivity_thresholds_m_s: Sequence[float] = (
        SENSITIVITY_SPEED_THRESHOLDS_M_S
    ),
) -> dict[str, Any]:
    """Intersect the existing SONIC guards with sustained base translation."""

    import numpy as np

    rows = inputs.sample_count
    values = np.asarray(targets, dtype=np.float64)
    source = np.asarray(inputs.source_targets_mujoco_rad, dtype=np.float64)
    if values.shape != (rows, 29) or source.shape != values.shape:
        raise ValueError("base translation screen requires [N,29] targets")
    if not np.isfinite(values).all():
        raise ValueError("base translation screen targets must be finite")
    if qualification_ticks <= 0:
        raise ValueError("qualification ticks must be positive")
    if not float(minimum_horizontal_speed_m_s) > 0.0:
        raise ValueError("minimum horizontal speed must be positive")
    velocity, position = _validate_state_arrays(
        rows=rows,
        base_velocity_m_s=base_velocity_m_s,
        base_position_xy_m=base_position_xy_m,
    )
    horizontal_speed = np.linalg.norm(velocity[:, :2], axis=1)
    previous_command = np.vstack([source[0], source[:-1]])
    handoff_delta = np.max(np.abs(values - previous_command), axis=1)
    handoff_ok = handoff_delta <= float(
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
    reference_motion = (
        np.asarray(reference.analog_available, dtype=bool)
        & np.isin(np.asarray(reference.phases), LOCOMOTION_PHASES)
        & (reference_displacement >= MOTION_REFERENCE_MIN_DISPLACEMENT_RAD)
    )
    candidate_safe_motion = handoff_ok & envelope_ok & reference_motion

    def threshold_result(threshold: float) -> dict[str, Any]:
        if not float(threshold) > 0.0:
            raise ValueError("sensitivity speed thresholds must be positive")
        translation = horizontal_speed >= float(threshold)
        eligible = candidate_safe_motion & translation
        eligible[0] = False
        runs = _true_runs(eligible)
        qualifying = [
            (start, end)
            for start, end in runs
            if end - start + 1 >= qualification_ticks
        ]
        longest = max(runs, key=lambda row: row[1] - row[0] + 1) if runs else None

        def mask_summary(mask: Any) -> dict[str, Any]:
            selected_mask = np.asarray(mask, dtype=bool).copy()
            selected_mask[0] = False
            selected_runs = _true_runs(selected_mask)
            selected_longest = max(
                (end - start + 1 for start, end in selected_runs), default=0
            )
            return {
                "sample_count": int(selected_mask.sum()),
                "run_count": len(selected_runs),
                "longest_run_ticks": int(selected_longest),
                "longest_run_s": float(selected_longest * CONTROL_DT_S),
            }

        translation_with_reference = translation & reference_motion
        return {
            "minimum_horizontal_speed_m_s": float(threshold),
            "base_translation_sample_count": int(translation.sum()),
            "eligible_sample_count": int(eligible.sum()),
            "eligible_run_count": len(runs),
            "longest_eligible_run_ticks": (
                0 if longest is None else int(longest[1] - longest[0] + 1)
            ),
            "longest_eligible_run_s": (
                0.0
                if longest is None
                else float((longest[1] - longest[0] + 1) * CONTROL_DT_S)
            ),
            "longest_eligible_run": (
                None
                if longest is None
                else _window_record(
                    start=longest[0],
                    end=longest[1],
                    inputs=inputs,
                    reference=reference,
                    horizontal_speed_m_s=horizontal_speed,
                    base_position_xy_m=position,
                    reference_displacement_rad=reference_displacement,
                    handoff_delta_rad=handoff_delta,
                )
            ),
            "qualifying_window_count": len(qualifying),
            "first_20_qualifying_windows": [
                _window_record(
                    start=start,
                    end=end,
                    inputs=inputs,
                    reference=reference,
                    horizontal_speed_m_s=horizontal_speed,
                    base_position_xy_m=position,
                    reference_displacement_rad=reference_displacement,
                    handoff_delta_rad=handoff_delta,
                )
                for start, end in qualifying[:20]
            ],
            "stage_intersections": {
                "base_translation_only": mask_summary(translation),
                "plus_causal_motion_reference": mask_summary(
                    translation_with_reference
                ),
                "plus_target_envelope": mask_summary(
                    translation_with_reference & envelope_ok
                ),
                "plus_handoff_and_envelope": mask_summary(eligible),
            },
            "nonexclusive_failure_counts_within_base_translation": {
                "causal_motion_reference_unavailable_or_hold": int(
                    (translation & ~reference_motion).sum()
                ),
                "candidate_outside_command_envelope": int(
                    (translation & ~envelope_ok).sum()
                ),
                "candidate_handoff_delta_too_large": int(
                    (translation & ~handoff_ok).sum()
                ),
            },
            "passed": bool(qualifying),
        }

    selected = threshold_result(float(minimum_horizontal_speed_m_s))
    thresholds = sorted(
        {
            float(minimum_horizontal_speed_m_s),
            *(float(value) for value in sensitivity_thresholds_m_s),
        }
    )
    return {
        "semantics": (
            "Eligibility uses only the current frozen SONIC proposal, current or "
            "past causal reference state, and same-tick policy-visible horizontal "
            "base velocity. Privileged base XY is excluded from selection and is "
            "used only to audit realized displacement inside selected runs."
        ),
        "qualification_ticks": int(qualification_ticks),
        "qualification_duration_s": float(qualification_ticks * CONTROL_DT_S),
        "motion_reference_min_displacement_rad": (
            MOTION_REFERENCE_MIN_DISPLACEMENT_RAD
        ),
        "locomotion_task_phases": list(LOCOMOTION_PHASES),
        "candidate_safe_motion_sample_count": int(candidate_safe_motion.sum()),
        "privileged_base_position_used_for_selection": False,
        "selected_threshold": selected,
        "threshold_sensitivity": [threshold_result(value) for value in thresholds],
        "passed": selected["passed"],
    }


def _run_cpu_target_stream(
    *,
    inputs: MappingInputs,
    reference: CausalReferenceStream,
    encoder: Any,
    decoder: Any,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np

    logged_actions = build_source_applied_action_history(inputs, inputs.sample_count)
    prepared = prepare_decoder_state(inputs)
    targets = np.empty((inputs.sample_count, 29), dtype=np.float64)
    digest = hashlib.sha256()
    started = time.perf_counter()
    for index in range(inputs.sample_count):
        encoder_input = np.asarray(
            [
                ENCODER_ASSEMBLER.assemble(
                    build_motion_encoder_blocks(inputs, reference, index)
                )
            ],
            dtype=np.float32,
        )
        token = encoder.run(
            None, {encoder.get_inputs()[0].name: encoder_input}
        )[0]
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
        raw = decoder.run(
            None, {decoder.get_inputs()[0].name: decoder_input}
        )[0].reshape(-1)
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
        digest.update(
            np.ascontiguousarray(targets[index], dtype=np.float32).tobytes()
        )
    elapsed = time.perf_counter() - started
    return targets, {
        "sample_count": inputs.sample_count,
        "model_forwards": inputs.sample_count * 2,
        "elapsed_wall_s": elapsed,
        "mean_wall_ms_per_encoder_decoder_pair": (
            elapsed * 1000.0 / inputs.sample_count
        ),
        "target_stream_float32_sha256": digest.hexdigest(),
        "all_outputs_finite": True,
    }


def _load_bound_state(s3_episode: Path) -> tuple[Any, Any, dict[str, Any]]:
    import numpy as np

    root = s3_episode / "state_stream"
    policy, policy_binding = _verified_npz(root, "policy")
    privileged, privileged_binding = _verified_npz(root, "privileged")
    policy_time = np.asarray(policy["sim_time_s"], dtype=np.float64)
    privileged_time = np.asarray(privileged["sim_time_s"], dtype=np.float64)
    if not np.array_equal(policy_time, privileged_time):
        raise ValueError("policy and privileged state times differ")
    if "base_velocity" not in policy or "qpos" not in privileged:
        raise ValueError("frozen state lacks base velocity or base position")
    return (
        np.asarray(policy["base_velocity"], dtype=np.float64),
        np.asarray(privileged["qpos"], dtype=np.float64)[:, :2],
        {
            "policy_state": policy_binding["file"],
            "privileged_state": privileged_binding["file"],
        },
    )


def _phase_speed_calibration(
    reference: CausalReferenceStream, base_velocity: Any
) -> dict[str, Any]:
    import numpy as np

    speed = np.linalg.norm(np.asarray(base_velocity)[:, :2], axis=1)
    phases = np.asarray(reference.phases)

    def metrics(mask: Any) -> dict[str, Any]:
        selected = speed[np.asarray(mask, dtype=bool)]
        return {
            "sample_count": int(selected.size),
            "minimum_m_s": float(selected.min()),
            "median_m_s": float(np.median(selected)),
            "p90_m_s": float(np.percentile(selected, 90.0)),
            "p95_m_s": float(np.percentile(selected, 95.0)),
            "maximum_m_s": float(selected.max()),
        }

    nontranslation_mask = np.isin(phases, NON_TRANSLATION_CALIBRATION_PHASES)
    nontranslation = metrics(nontranslation_mask)
    return {
        "all_samples": metrics(np.ones(speed.shape[0], dtype=bool)),
        "by_phase": {
            str(phase): metrics(phases == phase) for phase in sorted(set(phases))
        },
        "nontranslation_calibration_phases": list(
            NON_TRANSLATION_CALIBRATION_PHASES
        ),
        "nontranslation_phase_union": nontranslation,
        "selected_threshold_to_nontranslation_maximum_ratio": (
            BASE_TRANSLATION_MIN_HORIZONTAL_SPEED_M_S
            / nontranslation["maximum_m_s"]
        ),
        "threshold_is_development_calibrated_not_held_out": True,
        "sensitivity_includes_0_02_m_s": True,
    }


def run_base_translation_admission(
    *,
    s3_episode: Path = DEFAULT_S3_EPISODE,
    sonic_root: Path = DEFAULT_SONIC_RUN,
    source_a_root: Path = DEFAULT_SOURCE_A,
    causal_motion_report: Path = CAUSAL_MOTION_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Execute and persist the zero-physics base-translation admission."""

    import onnxruntime as ort

    s3_episode = s3_episode.resolve()
    sonic_root = sonic_root.resolve()
    source_a_root = source_a_root.resolve()
    causal_motion_report = causal_motion_report.resolve()
    output_path = output_path.resolve()
    inputs, input_bindings = load_mapping_inputs(
        s3_episode=s3_episode, source_a_root=source_a_root
    )
    action_indices, decisions, conditioning_bindings = load_task_conditioning(
        s3_episode, inputs.sample_count
    )
    reference = build_causal_reference_stream(inputs, action_indices)
    gate = build_source_non_regression_gate(inputs, source_a_root)
    base_velocity, base_position, state_bindings = _load_bound_state(s3_episode)
    _validate_state_arrays(
        rows=inputs.sample_count,
        base_velocity_m_s=base_velocity,
        base_position_xy_m=base_position,
    )

    authority = json.loads(causal_motion_report.read_text(encoding="utf-8"))
    claimed_content_hash = authority.get("content_sha256_excluding_this_field")
    authority_without_hash = dict(authority)
    authority_without_hash.pop("content_sha256_excluding_this_field", None)
    authority_content_ok = bool(
        claimed_content_hash
        and canonical_sha256(authority_without_hash) == claimed_content_hash
    )
    expected_target_hash = authority["sonic_cpu_shadow"][
        "stream_hashes_float32_concatenated"
    ]["targets"]

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
    targets, cpu_shadow = _run_cpu_target_stream(
        inputs=inputs,
        reference=reference,
        encoder=encoder,
        decoder=decoder,
    )
    cpu_shadow["expected_authority_target_stream_float32_sha256"] = (
        expected_target_hash
    )
    cpu_shadow["target_stream_matches_authority"] = bool(
        cpu_shadow["target_stream_float32_sha256"] == expected_target_hash
    )
    screen = screen_base_translation_takeover(
        targets=targets,
        inputs=inputs,
        reference=reference,
        gate=gate,
        base_velocity_m_s=base_velocity,
        base_position_xy_m=base_position,
    )
    admitted = bool(
        inputs.sample_count == 6209
        and authority_content_ok
        and cpu_shadow["target_stream_matches_authority"]
        and cpu_shadow["all_outputs_finite"]
        and screen["passed"]
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "classification": "admitted" if admitted else "not_admitted",
        "stop_reason": (
            "base_translation_physics_smoke_admitted"
            if admitted
            else "no_50_tick_guard_safe_base_translation_window"
        ),
        "implementation": _file_binding(Path(__file__)),
        "inputs": {
            "s3_episode": str(s3_episode),
            "sonic_root": str(sonic_root),
            "source_a_root": str(source_a_root),
            "bindings": {
                **input_bindings,
                **conditioning_bindings,
                **state_bindings,
                "causal_motion_authority": _file_binding(causal_motion_report),
                "encoder_model": _file_binding(encoder_path),
                "decoder_model": _file_binding(decoder_path),
            },
            "high_level_decisions": decisions,
        },
        "translation_signal_contract": {
            "eligibility_source": "policy_state.base_velocity[:,0:2]",
            "semantics": "same-tick measured free-base horizontal velocity",
            "minimum_horizontal_speed_m_s": (
                BASE_TRANSLATION_MIN_HORIZONTAL_SPEED_M_S
            ),
            "qualification_ticks": TAKEOVER_QUALIFICATION_TICKS,
            "qualification_duration_s": (
                TAKEOVER_QUALIFICATION_TICKS * CONTROL_DT_S
            ),
            "current_or_past_only": True,
            "privileged_position_selection_dependency": False,
            "privileged_position_audit_only": "privileged_state.qpos[:,0:2]",
            "threshold_status": "development_calibrated_not_held_out",
        },
        "speed_calibration": _phase_speed_calibration(reference, base_velocity),
        "frozen_gate": gate,
        "cpu_shadow": cpu_shadow,
        "base_translation_takeover_screen": screen,
        "gates": {
            "full_6209_reference_stream_built": inputs.sample_count == 6209,
            "causal_motion_authority_content_hash_valid": authority_content_ok,
            "full_cpu_shadow_executed": cpu_shadow["sample_count"] == 6209,
            "all_sonic_outputs_finite": cpu_shadow["all_outputs_finite"],
            "target_stream_matches_causal_motion_authority": cpu_shadow[
                "target_stream_matches_authority"
            ],
            "translation_signal_is_current_or_past_only": True,
            "privileged_base_position_excluded_from_selection": True,
            "guard_safe_50_tick_base_translation_window_available": screen[
                "passed"
            ],
            "base_translation_physics_smoke_admission_ready": admitted,
            "physics_executed": False,
            "actuation_enabled": False,
            "candidate_consumed_by_physics": False,
            "task_success_validated": False,
            "grasp_success_validated": False,
            "learning_validated": False,
            "production_accepted": False,
            "batch_authorized": False,
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "model_forwards": cpu_shadow["model_forwards"],
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "claim_boundary": (
            "This development-trajectory audit tests whether the existing causal "
            "reference and unmodified SONIC proposals contain a one-second guarded "
            "window during measured horizontal base translation. It does not alter "
            "the reference, authorize physics when the window is absent, or prove "
            "walking, task, grasp, learning, or production success."
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
    parser.add_argument(
        "--causal-motion-report", type=Path, default=CAUSAL_MOTION_REPORT
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_base_translation_admission(
        s3_episode=args.s3_episode,
        sonic_root=args.sonic_root,
        source_a_root=args.source_a_root,
        causal_motion_report=args.causal_motion_report,
        output_path=args.output,
        observed_at=args.observed_at,
    )
    screen = report["base_translation_takeover_screen"]["selected_threshold"]
    print(
        json.dumps(
            {
                "output": str(args.output),
                "classification": report["classification"],
                "stop_reason": report["stop_reason"],
                "longest_eligible_run_ticks": screen[
                    "longest_eligible_run_ticks"
                ],
                "qualifying_window_count": screen["qualifying_window_count"],
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
