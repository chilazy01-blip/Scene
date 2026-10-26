"""Run one bounded task-motion SONIC body-control smoke.

The heavy simulator/audit harness is reused from ``run_sonic_body_smoke``;
this module supplies the separately admitted causal motion reference, requires
50 consecutive motion-bearing shadow ticks, and rewrites the final protocol
and result with bindings to this runner.  SONIC still controls only the 29 body
actuators and the existing fail-closed guard remains the final command gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import run_sonic_body_smoke as base_smoke
from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .run_source_a_adapter_smoke import DEFAULT_S1_ROOT
from .run_source_a_native import DEFAULT_SOURCE_A_RUN, NativeCounters, read_json
from .contact_diagnostics import CategorizedContactAudit
from .sonic_causal_hold_shadow import build_causal_hold_encoder_blocks
from .sonic_causal_motion_reference import (
    LOCOMOTION_PHASES,
    MOTION_REFERENCE_MIN_DISPLACEMENT_RAD,
    OnlineCausalReferenceBuilder,
)
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    build_decoder_blocks,
    reorder_mujoco_to_isaaclab,
)
from .sonic_runtime_guard import GuardDecision
from .sonic_semantic_shadow import (
    DECODER_ASSEMBLER,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)


SCHEMA = "sonic-bounded-task-motion-physics-smoke/v1"
EXPECTED_ADMISSION_SCHEMA = "sonic-causal-motion-reference-shadow/v1"
MAXIMUM_SHADOW_TICKS = 600
DEFAULT_ADMISSION_REPORT = (
    base_smoke.DEFAULT_SONIC_RUN / "SONIC_CAUSAL_MOTION_REFERENCE_SHADOW.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_motion_smoke_20261019_v1"
)
_BASE_CLASSIFY = base_smoke._classify
_CURRENT_MOTION_OVERLAY: "OnlineSonicMotionActuationOverlay | None" = None


@dataclass(frozen=True)
class MotionRuntimeLimits:
    qualification_ticks: int = base_smoke.QUALIFICATION_TICKS
    maximum_shadow_ticks: int = MAXIMUM_SHADOW_TICKS
    maximum_active_ticks: int = base_smoke.MAX_ACTIVE_TICKS

    def validate(self) -> None:
        if self.qualification_ticks != base_smoke.QUALIFICATION_TICKS:
            raise ValueError("the admitted motion qualification is exactly 50 ticks")
        if self.maximum_shadow_ticks != MAXIMUM_SHADOW_TICKS:
            raise ValueError("the motion smoke shadow budget is exactly 600 ticks")
        if self.maximum_active_ticks != base_smoke.MAX_ACTIVE_TICKS:
            raise ValueError("the motion smoke active budget is exactly 100 ticks")


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def validate_motion_admission_report(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed unless the motion-reference report and dependencies match."""

    report = read_json(path)
    if report.get("schema") != EXPECTED_ADMISSION_SCHEMA:
        raise RuntimeError("unexpected SONIC motion-admission schema")
    content_hash = report.get("content_sha256_excluding_this_field")
    without_hash = dict(report)
    without_hash.pop("content_sha256_excluding_this_field", None)
    if content_hash != canonical_sha256(without_hash):
        raise RuntimeError("SONIC motion-admission content hash mismatch")
    required = (
        "full_6209_reference_stream_built",
        "future_data_independence_verified",
        "task_conditioned_0_9s_29_joint_reference_ready",
        "prediction_not_worse_than_hold_on_frozen_scopes",
        "reference_integrity_passed",
        "full_cpu_shadow_executed",
        "all_sonic_outputs_finite",
        "one_step_takeover_window_available",
        "motion_bearing_takeover_window_available",
        "runtime_guard_bound",
        "motion_physics_smoke_admission_ready",
    )
    failed = [name for name in required if report.get("gates", {}).get(name) is not True]
    if failed:
        raise RuntimeError(f"SONIC motion physical admission gates failed: {failed}")

    runtime = report.get("runtime_contract", {})
    if not (
        int(runtime.get("shadow_qualification_ticks", -1))
        == base_smoke.QUALIFICATION_TICKS
        and int(runtime.get("maximum_active_ticks", -1))
        == base_smoke.MAX_ACTIVE_TICKS
        and math.isclose(
            float(runtime.get("maximum_active_duration_s", -1)),
            base_smoke.MAX_ACTIVE_TICKS * CONTROL_DT_S,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and runtime.get("qualification_requires_motion_bearing_reference") is True
        and runtime.get("active_checks_repeat_every_tick") is True
        and runtime.get("output_clipping_or_rate_limiting") is False
        and runtime.get("dex3_commands_changed") is False
    ):
        raise RuntimeError("motion runtime contract is absent or inconsistent")

    records = {
        "causal_motion_reference": report.get("implementation", {}),
        "runtime_guard": runtime.get("implementation", {}),
        "encoder_model": report.get("inputs", {}).get("encoder_model", {}),
        "decoder_model": report.get("inputs", {}).get("decoder_model", {}),
    }
    for name, record in records.items():
        bound_path = Path(record.get("path", ""))
        if not bound_path.is_file() or sha256_file(bound_path) != record.get("sha256"):
            raise RuntimeError(f"{name} no longer matches motion admission")
    return report, {
        "admission_report": _binding(path),
        **{name: dict(record) for name, record in records.items()},
    }


class MotionTaskConditioner:
    """Expose the same two native high-level goals and update online task state."""

    direct = False

    def __init__(self, overlay: "OnlineSonicMotionActuationOverlay", pipeline: Any):
        self.overlay = overlay
        self.pick = pipeline.PICK_STANCE
        self.place = pipeline.PLACE_STANCE

    def pick_stance(self, _: Mapping[str, Any]):
        self.overlay.set_task_conditioning("approach", 0, self.pick)
        return self.pick

    def place_stance(self, _: Mapping[str, Any]):
        self.overlay.set_task_conditioning("carry", 1, self.place)
        return self.place


class OnlineSonicMotionActuationOverlay(base_smoke.OnlineSonicActuationOverlay):
    """Existing final-command seam with a causal rolling motion reference."""

    def __init__(self, **kwargs: Any) -> None:
        global _CURRENT_MOTION_OVERLAY

        super().__init__(**kwargs)
        self.reference_builder = OnlineCausalReferenceBuilder()
        self.task_phase = "pre_approach"
        self.high_level_action_index = -1
        self.high_level_goal_xyyaw: tuple[float, float, float] | None = None
        self.high_level_events: list[dict[str, Any]] = []
        self.consecutive_motion_shadow_passes = 0
        self.maximum_consecutive_motion_shadow_passes = 0
        self.motion_eligible_shadow_ticks = 0
        self.active_motion_reference_ticks = 0
        self.reference_build_wall_s = 0.0
        self.reference_build_max_ms = 0.0
        self.active_reference_displacements: list[float] = []
        self.activation_deferred_for_penetration = 0
        self.maximum_pre_activation_penetration_m = 0.0
        self._pipeline: Any | None = None
        _CURRENT_MOTION_OVERLAY = self

    def install(self, mujoco: Any) -> None:
        super().install(mujoco)
        from ik import pipeline

        if pipeline.COMMANDER is not None:
            raise RuntimeError("motion overlay requires an empty Source-A commander")
        self._pipeline = pipeline
        pipeline.COMMANDER = MotionTaskConditioner(self, pipeline)

    def uninstall(self) -> None:
        global _CURRENT_MOTION_OVERLAY

        if self._pipeline is not None:
            self._pipeline.COMMANDER = None
        self._pipeline = None
        super().uninstall()
        _CURRENT_MOTION_OVERLAY = None

    def _current_max_penetration(self, model: Any, data: Any) -> float:
        return max((max(0.0, -float(contact.dist)) for contact in data.contact), default=0.0)

    def set_task_conditioning(
        self, phase: str, action_index: int, target: Any
    ) -> None:
        xy, yaw = target
        self.task_phase = str(phase)
        self.high_level_action_index = int(action_index)
        self.high_level_goal_xyyaw = (float(xy[0]), float(xy[1]), float(yaw))
        self.high_level_events.append(
            {
                "phase": self.task_phase,
                "high_level_action_index": self.high_level_action_index,
                "base_pose_xyyaw": list(self.high_level_goal_xyyaw),
                "control_tick": self.control_ticks,
            }
        )

    def _infer(self, sim_time_s: float) -> tuple[Any, Any, dict[str, Any]]:
        np = self._np
        inputs = self._mapping_inputs()
        index = inputs.sample_count - 1
        reference_started = time.perf_counter()
        tick = self.reference_builder.append(
            position_mujoco_rad=self.positions[-1],
            velocity_mujoco_rad_s=self.velocities[-1],
            source_target_mujoco_rad=self.source_targets[-1],
            phase=self.task_phase,
            high_level_action_index=self.high_level_action_index,
        )
        reference_elapsed = time.perf_counter() - reference_started
        self.reference_build_wall_s += reference_elapsed
        self.reference_build_max_ms = max(
            self.reference_build_max_ms, reference_elapsed * 1000.0
        )
        started = time.perf_counter()
        blocks = build_causal_hold_encoder_blocks(inputs, index)
        blocks["motion_joint_positions_10frame_step5"] = (
            reorder_mujoco_to_isaaclab(tick.positions_mujoco_rad).reshape(-1)
        )
        blocks["motion_joint_velocities_10frame_step5"] = (
            reorder_mujoco_to_isaaclab(tick.velocities_mujoco_rad_s).reshape(-1)
        )
        encoder_input = np.asarray(
            [ENCODER_ASSEMBLER.assemble(blocks)], dtype=np.float32
        )
        token = self.encoder.run(
            None, {self.encoder.get_inputs()[0].name: encoder_input}
        )[0]
        decoder_input = np.asarray(
            [
                DECODER_ASSEMBLER.assemble(
                    build_decoder_blocks(
                        inputs,
                        index,
                        token_state=token,
                        logged_last_actions_isaaclab=np.asarray(
                            self.action_history, dtype=np.float64
                        ),
                    )
                )
            ],
            dtype=np.float32,
        )
        raw = self.decoder.run(
            None, {self.decoder.get_inputs()[0].name: decoder_input}
        )[0].reshape(-1)
        inference_elapsed = time.perf_counter() - started
        self.inference_wall_s += inference_elapsed
        self.model_forwards += 2
        if not (
            np.isfinite(encoder_input).all()
            and np.isfinite(token).all()
            and np.isfinite(decoder_input).all()
            and np.isfinite(raw).all()
        ):
            raise RuntimeError("non-finite online SONIC motion inference value")
        target = np.asarray(
            body_joint_target_from_raw_action(
                raw, phase=self.task_phase, sim_time_s=sim_time_s
            ).position_target_rad,
            dtype=np.float64,
        )
        self._hash_float32(self._hashes["encoder_inputs"], encoder_input)
        self._hash_float32(self._hashes["encoder_tokens"], token)
        self._hash_float32(self._hashes["decoder_inputs"], decoder_input)
        self._hash_float32(self._hashes["raw_actions"], raw)
        self._hash_float32(self._hashes["candidate_targets"], target)
        motion_eligible = bool(
            tick.analog_available
            and self.task_phase in LOCOMOTION_PHASES
            and tick.maximum_future_displacement_rad
            >= MOTION_REFERENCE_MIN_DISPLACEMENT_RAD
        )
        return raw, target, {
            "inference_wall_ms": inference_elapsed * 1000.0,
            "reference_build_wall_ms": reference_elapsed * 1000.0,
            "reference_analog_available": tick.analog_available,
            "reference_match_score": None
            if not math.isfinite(tick.match_score)
            else tick.match_score,
            "reference_neighbor_indices": list(tick.neighbor_indices),
            "reference_maximum_consumed_state_index": (
                tick.maximum_consumed_state_index
            ),
            "reference_maximum_future_displacement_rad": (
                tick.maximum_future_displacement_rad
            ),
            "motion_reference_eligible": motion_eligible,
            "task_phase": self.task_phase,
            "high_level_action_index": self.high_level_action_index,
            "high_level_goal_xyyaw": None
            if self.high_level_goal_xyyaw is None
            else list(self.high_level_goal_xyyaw),
        }

    def _control_tick(self, model: Any, data: Any, source_command: Any) -> Any:
        np = self._np
        if self.pending_stop_reason is not None:
            self.stop(self.pending_stop_reason)
        if self.activate_next_tick:
            current_penetration = self._current_max_penetration(model, data)
            self.maximum_pre_activation_penetration_m = max(
                self.maximum_pre_activation_penetration_m, current_penetration
            )
            if current_penetration <= base_smoke.MAX_PENETRATION_M:
                self.guard.activate()
                self.activate_next_tick = False
            else:
                self.activate_next_tick = False
                self.activation_deferred_for_penetration += 1
                self.consecutive_motion_shadow_passes = 0

        quaternion = np.asarray(data.qpos[3:7], dtype=np.float64).copy()
        norm = float(np.linalg.norm(quaternion))
        if not math.isfinite(norm) or not math.isclose(
            norm, 1.0, rel_tol=0.0, abs_tol=1e-5
        ):
            self.stop("non_unit_or_nonfinite_base_quaternion")
        self.positions.append(
            np.asarray(data.qpos[self._body_qpos_ids], dtype=np.float64).copy()
        )
        self.velocities.append(
            np.asarray(data.qvel[self._body_dof_ids], dtype=np.float64).copy()
        )
        self.quaternions.append(quaternion)
        self.angular_velocities.append(
            np.asarray(data.qvel[3:6], dtype=np.float64).copy()
        )
        self.source_targets.append(np.asarray(source_command, dtype=np.float64).copy())
        self.action_history.append(self._previous_action_row())
        raw, candidate, timing = self._infer(float(data.time))
        motion_eligible = bool(timing["motion_reference_eligible"])

        decision: GuardDecision | None
        dispatched = np.asarray(source_command, dtype=np.float64).copy()
        if self.guard.mode == "shadow":
            self.shadow_ticks += 1
            decision = None
            if self.previous_command is not None:
                decision = self.guard.observe_shadow(candidate, self.previous_command)
                if motion_eligible and decision.candidate_safe:
                    self.motion_eligible_shadow_ticks += 1
                    self.consecutive_motion_shadow_passes += 1
                else:
                    self.consecutive_motion_shadow_passes = 0
                self.maximum_consecutive_motion_shadow_passes = max(
                    self.maximum_consecutive_motion_shadow_passes,
                    self.consecutive_motion_shadow_passes,
                )
                if (
                    self.consecutive_motion_shadow_passes
                    >= self.limits.qualification_ticks
                    and self.guard.handoff_ready
                ):
                    self.activate_next_tick = True
            self.last_dispatched_source = "source_a"
            self.held_body_target = None
            self.previous_raw_sonic = None
            if (
                self.shadow_ticks >= self.limits.maximum_shadow_ticks
                and not self.activate_next_tick
            ):
                self.pending_stop_reason = "motion_shadow_budget_exhausted"
        elif self.guard.mode == "active":
            candidate_for_guard = (
                candidate if motion_eligible else np.full(29, np.nan)
            )
            decision = self.guard.evaluate_active(
                candidate_for_guard,
                self.previous_command,
                source_a_fallback=source_command,
            )
            self.active_ticks += 1
            if decision.transmit and decision.source == "sonic":
                dispatched = np.asarray(decision.target_rad, dtype=np.float64)
                self.last_dispatched_source = "sonic"
                self.previous_raw_sonic = np.asarray(raw, dtype=np.float64).copy()
                self.held_body_target = dispatched.copy()
                self.sonic_transmit_ticks += 1
                self.active_motion_reference_ticks += 1
                self.active_reference_displacements.append(
                    float(timing["reference_maximum_future_displacement_rad"])
                )
            elif decision.transmit and decision.source == "source_a":
                dispatched = np.asarray(decision.target_rad, dtype=np.float64)
                self.last_dispatched_source = "source_a_fallback"
                self.previous_raw_sonic = None
                self.held_body_target = dispatched.copy()
                self.fallback_transmit_ticks += 1
                self.pending_stop_reason = (
                    "motion_reference_lost_safe_fallback_latched"
                    if not motion_eligible
                    else "first_guard_rejection_safe_fallback_latched"
                )
            else:
                self.control_trace.append(
                    {
                        "control_tick": self.control_ticks,
                        "sim_time_s": float(data.time),
                        "decision": self._decision_record(decision),
                        **timing,
                    }
                )
                self.stop("first_guard_rejection_no_safe_fallback")
            if self.active_ticks >= self.limits.maximum_active_ticks:
                self.pending_stop_reason = "active_tick_budget_complete"
        else:
            self.stop(f"unexpected_guard_mode_{self.guard.mode}")

        delta = (
            None
            if self.previous_command is None
            else float(np.max(np.abs(dispatched - self.previous_command)))
        )
        self.control_trace.append(
            {
                "control_tick": self.control_ticks,
                "sim_time_s": float(data.time),
                "guard": self._decision_record(decision),
                "motion_consecutive_shadow_passes": (
                    self.consecutive_motion_shadow_passes
                ),
                "source_command_rad": source_command.tolist(),
                "candidate_target_rad": candidate.tolist(),
                "dispatched_source": self.last_dispatched_source,
                "dispatched_body_target_rad": dispatched.tolist(),
                "max_abs_delta_from_previous_dispatched_rad": delta,
                **timing,
            }
        )
        self.control_ticks += 1
        self._hash_float32(self._hashes["dispatched_body_targets"], dispatched)
        return dispatched

    def report(self) -> dict[str, Any]:
        report = super().report()
        report.update(
            {
                "task_phase": self.task_phase,
                "high_level_action_index": self.high_level_action_index,
                "high_level_goal_xyyaw": None
                if self.high_level_goal_xyyaw is None
                else list(self.high_level_goal_xyyaw),
                "high_level_events": self.high_level_events,
                "motion_eligible_shadow_ticks": self.motion_eligible_shadow_ticks,
                "consecutive_motion_shadow_passes": (
                    self.consecutive_motion_shadow_passes
                ),
                "maximum_consecutive_motion_shadow_passes": (
                    self.maximum_consecutive_motion_shadow_passes
                ),
                "active_motion_reference_ticks": (
                    self.active_motion_reference_ticks
                ),
                "minimum_active_reference_displacement_rad": None
                if not self.active_reference_displacements
                else min(self.active_reference_displacements),
                "maximum_active_reference_displacement_rad": None
                if not self.active_reference_displacements
                else max(self.active_reference_displacements),
                "reference_build_wall_s": self.reference_build_wall_s,
                "mean_reference_build_ms": 1000.0
                * self.reference_build_wall_s
                / max(self.control_ticks, 1),
                "maximum_reference_build_ms": self.reference_build_max_ms,
                "activation_deferred_for_penetration": (
                    self.activation_deferred_for_penetration
                ),
                "maximum_pre_activation_penetration_m": (
                    self.maximum_pre_activation_penetration_m
                ),
            }
        )
        return report


class MotionScopedCounters(NativeCounters):
    """Keep full shadow contact evidence but gate penetration only after takeover."""

    def __init__(
        self,
        mujoco: Any,
        ort: Any,
        max_physics_steps: int,
        max_sim_seconds: float,
        on_step: Any | None = None,
    ) -> None:
        if _CURRENT_MOTION_OVERLAY is None:
            raise RuntimeError("motion counters were created before the online overlay")
        self.motion_overlay = _CURRENT_MOTION_OVERLAY
        self.user_on_step = on_step
        self.overall_max_penetration_m = 0.0
        self.overall_max_contact_force_n = 0.0
        self.shadow_max_penetration_m = 0.0
        self.shadow_max_contact_force_n = 0.0
        self.active_physics_steps = 0
        self.active_contact_audit = CategorizedContactAudit()
        super().__init__(
            mujoco,
            ort,
            max_physics_steps,
            max_sim_seconds,
            on_step=self._scoped_on_step,
        )

    def _scoped_on_step(self, model: Any, data: Any, step: int, mujoco: Any) -> None:
        active = self.motion_overlay.last_dispatched_source == "sonic"
        self.overall_max_penetration_m = max(
            self.overall_max_penetration_m, self.max_penetration_m
        )
        self.overall_max_contact_force_n = max(
            self.overall_max_contact_force_n, self.max_contact_force_n
        )
        if active:
            import numpy as np

            self.active_physics_steps += 1
            for index, contact in enumerate(data.contact):
                force = np.zeros(6)
                mujoco.mj_contactForce(model, data, index, force)
                force_n = float(np.linalg.norm(force[:3]))
                body_a = mujoco.mj_id2name(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    int(model.geom_bodyid[contact.geom1]),
                ) or "world"
                body_b = mujoco.mj_id2name(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    int(model.geom_bodyid[contact.geom2]),
                ) or "world"
                geom_a = mujoco.mj_id2name(
                    model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom1)
                ) or f"geom_{int(contact.geom1)}"
                geom_b = mujoco.mj_id2name(
                    model, mujoco.mjtObj.mjOBJ_GEOM, int(contact.geom2)
                ) or f"geom_{int(contact.geom2)}"
                self.active_contact_audit.observe(
                    step=step,
                    sim_time_s=float(data.time),
                    body_a=body_a,
                    body_b=body_b,
                    geom_a=geom_a,
                    geom_b=geom_b,
                    distance_m=float(contact.dist),
                    force_n=force_n,
                )
        else:
            self.shadow_max_penetration_m = max(
                self.shadow_max_penetration_m, self.max_penetration_m
            )
            self.shadow_max_contact_force_n = max(
                self.shadow_max_contact_force_n, self.max_contact_force_n
            )
            self.max_penetration_m = 0.0
            self.max_contact_force_n = 0.0
        if self.user_on_step is not None:
            self.user_on_step(model, data, step, mujoco)

    def close(self) -> dict[str, Any]:
        report = super().close()
        all_phase_categories = report["contact_categories"]
        report.update(
            {
                "active_physics_steps": self.active_physics_steps,
                "overall_max_penetration_m": self.overall_max_penetration_m,
                "overall_max_contact_force_n": self.overall_max_contact_force_n,
                "shadow_max_penetration_m": self.shadow_max_penetration_m,
                "shadow_max_contact_force_n": self.shadow_max_contact_force_n,
                "all_phase_contact_categories": all_phase_categories,
                "contact_categories": self.active_contact_audit.report(),
            }
        )
        return report


def _motion_classify(
    *,
    source_result: Mapping[str, Any],
    overlay: Mapping[str, Any],
    metrics: Mapping[str, Any],
    physical: Mapping[str, Any],
    unexpected_error: str | None,
) -> tuple[str, dict[str, bool]]:
    _, gates = _BASE_CLASSIFY(
        source_result=source_result,
        overlay=overlay,
        metrics=metrics,
        physical=physical,
        unexpected_error=unexpected_error,
    )
    gates.update(
        {
            "motion_shadow_qualification_completed": int(
                overlay["maximum_consecutive_motion_shadow_passes"]
            )
            >= base_smoke.QUALIFICATION_TICKS,
            "motion_reference_present_on_every_sonic_tick": int(
                overlay["active_motion_reference_ticks"]
            )
            == int(overlay["sonic_transmit_ticks"]),
            "active_reference_exceeded_motion_threshold": (
                overlay["minimum_active_reference_displacement_rad"] is not None
                and float(overlay["minimum_active_reference_displacement_rad"])
                >= MOTION_REFERENCE_MIN_DISPLACEMENT_RAD
            ),
            "active_contact_scope_has_all_substeps": int(
                metrics.get("active_physics_steps", -1)
            )
            == int(overlay["sonic_transmit_ticks"])
            * base_smoke.CONTROL_DECIMATION,
        }
    )
    if not gates["no_unexpected_error"]:
        return "invalid", gates
    return ("passed" if all(gates.values()) else "diagnostic"), gates


def _rewrite_authoritative_documents(output_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    protocol_path = output_dir / "PROTOCOL.json"
    protocol = read_json(protocol_path)
    protocol.update(
        {
            "schema": "sonic-bounded-task-motion-physics-smoke-protocol/v1",
            "scope": (
                "one simulator-only task-motion body-control window; no full-task "
                "or grasp claim"
            ),
            "maximum_shadow_ticks": MAXIMUM_SHADOW_TICKS,
            "motion_reference_gate": {
                "analog_reference_required": True,
                "eligible_phases": list(LOCOMOTION_PHASES),
                "minimum_0_9s_joint_displacement_rad": (
                    MOTION_REFERENCE_MIN_DISPLACEMENT_RAD
                ),
                "consecutive_safe_motion_ticks": base_smoke.QUALIFICATION_TICKS,
            },
            "physical_gate_scope": {
                "finite_state_pelvis_upright_external_wrench_and_continuity": (
                    "entire shadow and active run"
                ),
                "penetration_and_contact_force": (
                    "shadow values are recorded as Source-A baseline evidence; "
                    "the current state must pass 10 mm before takeover, and the "
                    "unchanged 10 mm / 600 N hard stops apply to every active substep"
                ),
                "thresholds_relaxed": False,
            },
        }
    )
    protocol["bindings"]["motion_runner"] = _binding(Path(__file__))
    protocol["bindings"]["base_physics_harness"] = _binding(
        Path(base_smoke.__file__)
    )
    write_json_atomic(protocol_path, protocol)

    report["schema"] = SCHEMA
    report["artifacts"]["protocol"] = _binding(protocol_path)
    report["artifacts"]["motion_runner"] = _binding(Path(__file__))
    report["artifacts"]["base_physics_harness"] = _binding(Path(base_smoke.__file__))
    report["motion_reference_smoke"] = True
    report["claim_boundary"] = (
        "A pass proves only one bounded simulator window in which a causal, "
        "task-conditioned non-hold reference drove SONIC through the guarded 29-body "
        "actuator seam. It does not prove approach completion, grasp, the full task, "
        "generalization, production data quality, or learning value."
    )
    report.pop("content_sha256_excluding_this_field", None)
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_dir / "RESULT.json", report)
    return report


def run_motion_smoke(
    *,
    output_dir: Path,
    source_a_run: Path,
    baseline_result_path: Path,
    admission_report_path: Path,
    seed: int,
    episode_index: int,
) -> dict[str, Any]:
    original = {
        "RuntimeLimits": base_smoke.RuntimeLimits,
        "OnlineSonicActuationOverlay": base_smoke.OnlineSonicActuationOverlay,
        "validate_admission_report": base_smoke.validate_admission_report,
        "_classify": base_smoke._classify,
        "NativeCounters": base_smoke.NativeCounters,
        "SCHEMA": base_smoke.SCHEMA,
    }
    base_smoke.RuntimeLimits = MotionRuntimeLimits
    base_smoke.OnlineSonicActuationOverlay = OnlineSonicMotionActuationOverlay
    base_smoke.validate_admission_report = validate_motion_admission_report
    base_smoke._classify = _motion_classify
    base_smoke.NativeCounters = MotionScopedCounters
    base_smoke.SCHEMA = SCHEMA
    try:
        report = base_smoke.run_smoke(
            output_dir=output_dir,
            source_a_run=source_a_run,
            baseline_result_path=baseline_result_path,
            admission_report_path=admission_report_path,
            seed=seed,
            episode_index=episode_index,
        )
    finally:
        for name, value in original.items():
            setattr(base_smoke, name, value)
    return _rewrite_authoritative_documents(output_dir, report)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-a-run", type=Path, default=DEFAULT_SOURCE_A_RUN)
    parser.add_argument(
        "--baseline-result",
        type=Path,
        default=DEFAULT_S1_ROOT / "source_a_native_01" / "RESULT.json",
    )
    parser.add_argument(
        "--admission-report", type=Path, default=DEFAULT_ADMISSION_REPORT
    )
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--episode-index", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    try:
        report = run_motion_smoke(
            output_dir=args.output_dir,
            source_a_run=args.source_a_run,
            baseline_result_path=args.baseline_result,
            admission_report_path=args.admission_report,
            seed=args.seed,
            episode_index=args.episode_index,
        )
    except BaseException:
        error = traceback.format_exc()
        write_json_atomic(
            args.output_dir / "RUNNER_FAILURE.json",
            {
                "schema": "sonic-task-motion-smoke-runner-failure/v1",
                "error": error,
                "production_accepted": False,
                "task_success_validated": False,
            },
        )
        print(error, file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "classification": report["classification"],
                "physics_smoke_passed": report["physics_smoke_passed"],
                "physics_steps": report["physical"]["physics_steps"],
                "shadow_ticks": report["overlay"]["shadow_ticks"],
                "motion_qualification_ticks": report["overlay"][
                    "maximum_consecutive_motion_shadow_passes"
                ],
                "active_ticks": report["overlay"]["active_ticks"],
                "sonic_transmit_ticks": report["overlay"][
                    "sonic_transmit_ticks"
                ],
                "stop_reason": report["stop_reason"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["classification"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
