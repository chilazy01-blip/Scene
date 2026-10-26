"""Run one bounded SONIC body-control smoke inside the pinned Source-A scene.

The runtime seam is deliberately placed immediately before ``mujoco.mj_step``.
At that point Source A has already applied its body target and arm gravity
compensation, so the guard evaluates the exact 29-joint command that would be
sent to physics.  During shadow qualification Source A remains the sole body
controller.  Once qualified, a safe SONIC target replaces only the 29 body
actuators; all hand actuators remain on the untouched Source-A/Dex3 path.

This runner is a two-second simulator smoke, not a task or production-data
claim.  It never clips a SONIC output into compliance and stops on the first
guard, state, contact, or fixed-budget exit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import resource
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .audit_candidates import canonical_sha256, sha256_file, write_json_atomic
from .run_source_a_adapter_smoke import DEFAULT_S1_ROOT
from .run_source_a_native import (
    DEFAULT_SOURCE_A_RUN,
    NativeCounters,
    json_safe,
    read_json,
    verify_source_contract,
)
from .sonic_causal_reference_diagnostic import (
    build_causal_measured_state_hold_encoder_blocks,
)
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    DEFAULT_SONIC_RUN,
    MappingInputs,
    build_decoder_blocks,
    reorder_mujoco_to_isaaclab,
)
from .sonic_runtime_guard import GuardDecision, SonicRuntimeGuard
from .sonic_semantic_shadow import (
    ACTION_SCALES,
    DECODER_ASSEMBLER,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_shadow import SONIC_BODY_JOINT_ORDER


SCHEMA = "sonic-bounded-body-physics-smoke/v1"
DEFAULT_ADMISSION_REPORT = DEFAULT_SONIC_RUN / "SONIC_CAUSAL_TAKEOVER_SHADOW.json"
DEFAULT_OUTPUT_ROOT = Path(
    "/data/wsj/main/scene_runs/codex_trellis_v2/"
    "embodied_data_stability_sonic_physics_smoke_20261019_v1"
)
CONTROL_DECIMATION = 4
CONTROL_RATE_HZ = 50
PHYSICS_RATE_HZ = 200
QUALIFICATION_TICKS = 50
MAX_SHADOW_TICKS = 100
MAX_ACTIVE_TICKS = 100
MAX_PENETRATION_M = 0.010
MAX_CONTACT_FORCE_N = 600.0
MIN_PELVIS_HEIGHT_M = 0.65
EXPECTED_ADMISSION_SCHEMA = "sonic-causal-takeover-shadow/v1"


@dataclass(frozen=True)
class RuntimeLimits:
    qualification_ticks: int = QUALIFICATION_TICKS
    maximum_shadow_ticks: int = MAX_SHADOW_TICKS
    maximum_active_ticks: int = MAX_ACTIVE_TICKS

    def validate(self) -> None:
        if self.qualification_ticks != QUALIFICATION_TICKS:
            raise ValueError("the admitted qualification period is exactly 50 ticks")
        if self.maximum_shadow_ticks < self.qualification_ticks:
            raise ValueError("shadow budget must cover the qualification period")
        if not 0 < self.maximum_active_ticks <= MAX_ACTIVE_TICKS:
            raise ValueError("active smoke budget must be in [1,100] ticks")


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def inverse_target_to_raw_action(target_mujoco_rad: Any) -> Any:
    """Map an already final MuJoCo-order body command into raw IsaacLab order."""

    import numpy as np

    target = np.asarray(target_mujoco_rad, dtype=np.float64)
    if target.shape != (29,) or not np.isfinite(target).all():
        raise ValueError("body target must be one finite 29-vector")
    raw_mujoco = (target - np.asarray(DEFAULT_ANGLES)) / np.asarray(ACTION_SCALES)
    return reorder_mujoco_to_isaaclab(raw_mujoco)


def validate_admission_report(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed unless the CPU admission and its bound files are intact."""

    report = read_json(path)
    if report.get("schema") != EXPECTED_ADMISSION_SCHEMA:
        raise RuntimeError("unexpected SONIC admission-report schema")
    required_gates = (
        "full_6209_frame_stream_executed",
        "future_data_independence_verified",
        "all_outputs_finite",
        "one_step_takeover_window_available",
        "runtime_guard_bound",
        "physics_smoke_admission_ready",
    )
    failed = [name for name in required_gates if report.get("gates", {}).get(name) is not True]
    if failed:
        raise RuntimeError(f"SONIC physical admission gates failed: {failed}")

    physical = report.get("physics_smoke_contract", {})
    if not (
        physical.get("authorized_by_this_report") is True
        and int(physical.get("maximum_active_ticks", -1)) == MAX_ACTIVE_TICKS
        and math.isclose(
            float(physical.get("maximum_active_duration_s", -1)),
            MAX_ACTIVE_TICKS * CONTROL_DT_S,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        and physical.get("start_only_after_runtime_shadow_qualification") is True
        and physical.get("stop_on_first_guard_rejection") is True
        and physical.get("dex3_commands_changed") is False
    ):
        raise RuntimeError("physical smoke contract is absent or inconsistent")

    runtime = report.get("runtime_contract", {})
    guard_path = Path(runtime.get("implementation", {}).get("path", ""))
    expected_guard_hash = runtime.get("implementation", {}).get("sha256")
    if not guard_path.is_file() or sha256_file(guard_path) != expected_guard_hash:
        raise RuntimeError("runtime guard no longer matches the admitted implementation")
    if int(runtime.get("shadow_qualification_ticks", -1)) != QUALIFICATION_TICKS:
        raise RuntimeError("runtime qualification period differs from admission")
    if runtime.get("output_clipping_or_rate_limiting") is not False:
        raise RuntimeError("admission does not preserve raw candidate outputs")

    implementation_path = Path(report.get("implementation", {}).get("path", ""))
    expected_implementation_hash = report.get("implementation", {}).get("sha256")
    if (
        not implementation_path.is_file()
        or sha256_file(implementation_path) != expected_implementation_hash
    ):
        raise RuntimeError("causal shadow implementation no longer matches admission")

    for key in ("encoder_model", "decoder_model"):
        record = report.get("inputs", {}).get(key, {})
        model_path = Path(record.get("path", ""))
        if not model_path.is_file() or sha256_file(model_path) != record.get("sha256"):
            raise RuntimeError(f"{key} no longer matches the admitted model")

    return report, {
        "admission_report": _binding(path),
        "causal_shadow_implementation": _binding(implementation_path),
        "runtime_guard": _binding(guard_path),
        "encoder_model": report["inputs"]["encoder_model"],
        "decoder_model": report["inputs"]["decoder_model"],
    }


class OnlineSonicActuationOverlay:
    """Final-command MuJoCo hook for one qualified, bounded smoke."""

    def __init__(
        self,
        *,
        admission: Mapping[str, Any],
        encoder: Any,
        decoder: Any,
        limits: RuntimeLimits,
        stop: Any,
    ) -> None:
        import numpy as np

        limits.validate()
        envelope = admission["frozen_gate"]["allowed_command_envelope"]
        self.guard = SonicRuntimeGuard(
            lower_rad=envelope["admission_lower_rad"],
            upper_rad=envelope["admission_upper_rad"],
            max_abs_delta_rad=admission["frozen_gate"][
                "allowed_global_max_abs_delta_rad"
            ],
            qualification_ticks=limits.qualification_ticks,
        )
        self.encoder = encoder
        self.decoder = decoder
        self.limits = limits
        self.stop = stop
        self._np = np
        self._old_step: Any | None = None
        self._mujoco: Any | None = None
        self._bound_model: Any | None = None
        self._body_actuator_ids: Any | None = None
        self._body_qpos_ids: Any | None = None
        self._body_dof_ids: Any | None = None
        self._hand_actuator_ids: Any | None = None
        self.physics_calls = 0
        self.control_ticks = 0
        self.shadow_ticks = 0
        self.active_ticks = 0
        self.sonic_transmit_ticks = 0
        self.fallback_transmit_ticks = 0
        self.activate_next_tick = False
        self.pending_stop_reason: str | None = None
        self.previous_command: Any | None = None
        self.previous_raw_sonic: Any | None = None
        self.last_dispatched_source = "source_a"
        self.held_body_target: Any | None = None
        self.dex3_write_violations = 0
        self.positions: list[Any] = []
        self.velocities: list[Any] = []
        self.quaternions: list[Any] = []
        self.angular_velocities: list[Any] = []
        self.source_targets: list[Any] = []
        self.action_history: list[Any] = []
        self.control_trace: list[dict[str, Any]] = []
        self._hashes = {
            name: hashlib.sha256()
            for name in (
                "encoder_inputs",
                "encoder_tokens",
                "decoder_inputs",
                "raw_actions",
                "candidate_targets",
                "dispatched_body_targets",
            )
        }
        self.model_forwards = 0
        self.inference_wall_s = 0.0

    def install(self, mujoco: Any) -> None:
        if self._old_step is not None:
            raise RuntimeError("SONIC overlay is already installed")
        self._mujoco = mujoco
        self._old_step = mujoco.mj_step
        overlay = self

        def guarded_step(model: Any, data: Any, *args: Any, **kwargs: Any) -> None:
            if args or kwargs:
                raise RuntimeError("SONIC smoke expects one unqualified MuJoCo step")
            overlay._before_physics(model, data)
            overlay._old_step(model, data)
            overlay.physics_calls += 1

        mujoco.mj_step = guarded_step

    def uninstall(self) -> None:
        if self._old_step is not None and self._mujoco is not None:
            self._mujoco.mj_step = self._old_step
        self._old_step = None
        self._mujoco = None

    def _bind(self, model: Any) -> None:
        np = self._np
        mujoco = self._mujoco
        actuator_ids = []
        qpos_ids = []
        dof_ids = []
        for name in SONIC_BODY_JOINT_ORDER:
            actuator = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, name)
            joint = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
            if actuator < 0 or joint < 0:
                raise RuntimeError(f"online body seam is missing {name}")
            actuator_ids.append(int(actuator))
            qpos_ids.append(int(model.jnt_qposadr[joint]))
            dof_ids.append(int(model.jnt_dofadr[joint]))
        hand_ids = []
        for actuator in range(int(model.nu)):
            name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_ACTUATOR, actuator) or ""
            if "hand" in name or "finger" in name:
                hand_ids.append(actuator)
        if set(actuator_ids) & set(hand_ids):
            raise RuntimeError("body and hand actuator seams overlap")
        if not hand_ids:
            raise RuntimeError("the Source-A scene exposes no independent hand actuators")
        self._body_actuator_ids = np.asarray(actuator_ids, dtype=np.int64)
        self._body_qpos_ids = np.asarray(qpos_ids, dtype=np.int64)
        self._body_dof_ids = np.asarray(dof_ids, dtype=np.int64)
        self._hand_actuator_ids = np.asarray(hand_ids, dtype=np.int64)
        self._bound_model = model

    @staticmethod
    def _hash_float32(hasher: Any, values: Any) -> None:
        import numpy as np

        hasher.update(np.asarray(values, dtype=np.float32).tobytes())

    def _mapping_inputs(self) -> MappingInputs:
        np = self._np
        rows = len(self.positions)
        return MappingInputs(
            times_s=np.arange(rows, dtype=np.float64) * CONTROL_DT_S,
            body_position_mujoco_rad=np.asarray(self.positions, dtype=np.float64),
            body_velocity_mujoco_rad_s=np.asarray(self.velocities, dtype=np.float64),
            base_quaternion_wxyz=np.asarray(self.quaternions, dtype=np.float64),
            base_angular_velocity_rad_s=np.asarray(
                self.angular_velocities, dtype=np.float64
            ),
            source_targets_mujoco_rad=np.asarray(
                self.source_targets, dtype=np.float64
            ),
            phase_events=(),
            source_model_joint_order=SONIC_BODY_JOINT_ORDER,
            source_actuator_order=SONIC_BODY_JOINT_ORDER,
        )

    def _infer(self, sim_time_s: float) -> tuple[Any, Any, dict[str, float]]:
        np = self._np
        inputs = self._mapping_inputs()
        index = inputs.sample_count - 1
        started = time.perf_counter()
        encoder_values = ENCODER_ASSEMBLER.assemble(
            build_causal_measured_state_hold_encoder_blocks(inputs, index)
        )
        encoder_input = np.asarray([encoder_values], dtype=np.float32)
        token = self.encoder.run(
            None, {self.encoder.get_inputs()[0].name: encoder_input}
        )[0]
        decoder_values = DECODER_ASSEMBLER.assemble(
            build_decoder_blocks(
                inputs,
                index,
                token_state=token,
                logged_last_actions_isaaclab=np.asarray(
                    self.action_history, dtype=np.float64
                ),
            )
        )
        decoder_input = np.asarray([decoder_values], dtype=np.float32)
        raw = self.decoder.run(
            None, {self.decoder.get_inputs()[0].name: decoder_input}
        )[0].reshape(-1)
        elapsed = time.perf_counter() - started
        self.inference_wall_s += elapsed
        self.model_forwards += 2
        if not (
            np.isfinite(encoder_input).all()
            and np.isfinite(token).all()
            and np.isfinite(decoder_input).all()
            and np.isfinite(raw).all()
        ):
            raise RuntimeError("non-finite online SONIC inference value")
        target = np.asarray(
            body_joint_target_from_raw_action(
                raw, phase="pre_approach", sim_time_s=sim_time_s
            ).position_target_rad,
            dtype=np.float64,
        )
        self._hash_float32(self._hashes["encoder_inputs"], encoder_input)
        self._hash_float32(self._hashes["encoder_tokens"], token)
        self._hash_float32(self._hashes["decoder_inputs"], decoder_input)
        self._hash_float32(self._hashes["raw_actions"], raw)
        self._hash_float32(self._hashes["candidate_targets"], target)
        return raw, target, {"inference_wall_ms": elapsed * 1000.0}

    def _previous_action_row(self) -> Any:
        np = self._np
        if self.previous_command is None:
            return np.zeros(29, dtype=np.float64)
        if self.last_dispatched_source == "sonic":
            if self.previous_raw_sonic is None:
                raise RuntimeError("SONIC dispatch has no exact raw-action history")
            return np.asarray(self.previous_raw_sonic, dtype=np.float64)
        return inverse_target_to_raw_action(self.previous_command)

    @staticmethod
    def _decision_record(decision: GuardDecision | None) -> dict[str, Any]:
        if decision is None:
            return {
                "mode": "shadow",
                "candidate_safe": False,
                "transmit": False,
                "source": None,
                "reason": "first_tick_has_no_previous_command",
                "consecutive_shadow_passes": 0,
                "handoff_ready": False,
            }
        return {
            "mode": decision.mode,
            "candidate_safe": decision.candidate_safe,
            "transmit": decision.transmit,
            "source": decision.source,
            "reason": decision.reason,
            "consecutive_shadow_passes": decision.consecutive_shadow_passes,
            "handoff_ready": decision.handoff_ready,
        }

    def _control_tick(self, model: Any, data: Any, source_command: Any) -> Any:
        np = self._np
        if self.pending_stop_reason is not None:
            self.stop(self.pending_stop_reason)
        if self.activate_next_tick:
            self.guard.activate()
            self.activate_next_tick = False

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

        decision: GuardDecision | None
        dispatched = np.asarray(source_command, dtype=np.float64).copy()
        if self.guard.mode == "shadow":
            self.shadow_ticks += 1
            decision = None
            if self.previous_command is not None:
                decision = self.guard.observe_shadow(candidate, self.previous_command)
                if decision.handoff_ready:
                    self.activate_next_tick = True
            self.last_dispatched_source = "source_a"
            self.held_body_target = None
            self.previous_raw_sonic = None
            if (
                self.shadow_ticks >= self.limits.maximum_shadow_ticks
                and not self.activate_next_tick
            ):
                self.pending_stop_reason = "shadow_qualification_budget_exhausted"
        elif self.guard.mode == "active":
            decision = self.guard.evaluate_active(
                candidate,
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
            elif decision.transmit and decision.source == "source_a":
                dispatched = np.asarray(decision.target_rad, dtype=np.float64)
                self.last_dispatched_source = "source_a_fallback"
                self.previous_raw_sonic = None
                self.held_body_target = dispatched.copy()
                self.fallback_transmit_ticks += 1
                self.pending_stop_reason = "first_guard_rejection_safe_fallback_latched"
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

    def _before_physics(self, model: Any, data: Any) -> None:
        np = self._np
        if self._bound_model is None:
            self._bind(model)
        elif model is not self._bound_model:
            raise RuntimeError("secondary model entered the SONIC actuation hook")
        hand_before = np.asarray(data.ctrl[self._hand_actuator_ids]).copy()
        source_command = np.asarray(data.ctrl[self._body_actuator_ids], dtype=np.float64)
        at_control_tick = self.physics_calls % CONTROL_DECIMATION == 0
        if at_control_tick:
            dispatched = self._control_tick(model, data, source_command)
            if self.last_dispatched_source in {"sonic", "source_a_fallback"}:
                data.ctrl[self._body_actuator_ids] = dispatched
        elif self.last_dispatched_source in {"sonic", "source_a_fallback"}:
            data.ctrl[self._body_actuator_ids] = self.held_body_target

        hand_after = np.asarray(data.ctrl[self._hand_actuator_ids])
        if not np.array_equal(hand_before, hand_after):
            self.dex3_write_violations += 1
            self.stop("sonic_overlay_modified_hand_actuator")
        self.previous_command = np.asarray(
            data.ctrl[self._body_actuator_ids], dtype=np.float64
        ).copy()

    def report(self) -> dict[str, Any]:
        return {
            "control_rate_hz": CONTROL_RATE_HZ,
            "physics_rate_hz": PHYSICS_RATE_HZ,
            "control_ticks": self.control_ticks,
            "shadow_ticks": self.shadow_ticks,
            "active_ticks": self.active_ticks,
            "sonic_transmit_ticks": self.sonic_transmit_ticks,
            "source_a_fallback_transmit_ticks": self.fallback_transmit_ticks,
            "physics_calls_completed": self.physics_calls,
            "model_forwards": self.model_forwards,
            "inference_wall_s": self.inference_wall_s,
            "mean_inference_pair_ms": (
                1000.0 * self.inference_wall_s / max(self.control_ticks, 1)
            ),
            "final_guard_mode": self.guard.mode,
            "consecutive_shadow_passes": self.guard.consecutive_shadow_passes,
            "pending_stop_reason": self.pending_stop_reason,
            "dex3_write_violations": self.dex3_write_violations,
            "body_actuator_ids": (
                []
                if self._body_actuator_ids is None
                else self._body_actuator_ids.tolist()
            ),
            "hand_actuator_ids": (
                []
                if self._hand_actuator_ids is None
                else self._hand_actuator_ids.tolist()
            ),
            "stream_hashes_float32_concatenated": {
                name: digest.hexdigest() for name, digest in self._hashes.items()
            },
        }


def _load_onnx_sessions(admission: Mapping[str, Any]) -> tuple[Any, Any]:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    encoder = ort.InferenceSession(
        admission["inputs"]["encoder_model"]["path"],
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    decoder = ort.InferenceSession(
        admission["inputs"]["decoder_model"]["path"],
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return encoder, decoder


def _classify(
    *,
    source_result: Mapping[str, Any],
    overlay: Mapping[str, Any],
    metrics: Mapping[str, Any],
    physical: Mapping[str, Any],
    unexpected_error: str | None,
) -> tuple[str, dict[str, bool]]:
    stop_reason = source_result.get("abort")
    gates = {
        "no_unexpected_error": unexpected_error is None and not source_result.get("error"),
        "shadow_qualification_completed": (
            int(overlay["consecutive_shadow_passes"]) >= QUALIFICATION_TICKS
        ),
        "sonic_entered_physics": int(overlay["sonic_transmit_ticks"]) > 0,
        "active_tick_budget_completed": (
            stop_reason == "active_tick_budget_complete"
            and int(overlay["active_ticks"]) == MAX_ACTIVE_TICKS
            and int(overlay["sonic_transmit_ticks"]) == MAX_ACTIVE_TICKS
        ),
        "no_guard_fallback": int(overlay["source_a_fallback_transmit_ticks"]) == 0,
        "dex3_untouched_by_overlay": int(overlay["dex3_write_violations"]) == 0,
        "finite": int(metrics["nonfinite_steps"]) == 0,
        "no_external_wrench": int(metrics["external_wrench_violations"]) == 0,
        "state_continuity": int(metrics["state_continuity_violations"]) == 0,
        "pelvis_height": float(physical["minimum_pelvis_height_m"]) >= MIN_PELVIS_HEIGHT_M,
        "upright": float(physical["minimum_pelvis_up_component"]) >= 0.5,
        "penetration": float(metrics["max_penetration_m"]) <= MAX_PENETRATION_M,
        "contact_force": float(metrics["max_contact_force_n"]) <= MAX_CONTACT_FORCE_N,
    }
    if not gates["no_unexpected_error"]:
        return "invalid", gates
    return ("passed" if all(gates.values()) else "diagnostic"), gates


def run_smoke(
    *,
    output_dir: Path,
    source_a_run: Path,
    baseline_result_path: Path,
    admission_report_path: Path,
    seed: int,
    episode_index: int,
) -> dict[str, Any]:
    started = time.monotonic()
    limits = RuntimeLimits()
    limits.validate()
    admission, admission_bindings = validate_admission_report(admission_report_path)
    branch = source_a_run / "branches" / "A"
    source = branch / "source"
    source_contract_path = branch / "SOURCE_CONTRACT.json"
    source_contract = read_json(source_contract_path)
    source_verification = verify_source_contract(source, source_contract)
    baseline = read_json(baseline_result_path)
    if baseline.get("native_reproduction_passed") is not True:
        raise RuntimeError("pinned Source-A baseline did not pass")

    protocol = {
        "schema": "sonic-bounded-body-physics-smoke-protocol/v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "attempt_limit": 1,
        "seed": seed,
        "episode_index": episode_index,
        "scope": "simulator-only body-control smoke; no task or grasp claim",
        "control_rate_hz": CONTROL_RATE_HZ,
        "physics_rate_hz": PHYSICS_RATE_HZ,
        "qualification_ticks": limits.qualification_ticks,
        "maximum_shadow_ticks": limits.maximum_shadow_ticks,
        "maximum_active_ticks": limits.maximum_active_ticks,
        "maximum_active_duration_s": limits.maximum_active_ticks / CONTROL_RATE_HZ,
        "command_gates": {
            "all_29_finite": True,
            "maximum_50hz_delta_rad": admission["frozen_gate"][
                "allowed_global_max_abs_delta_rad"
            ],
            "envelope": admission["frozen_gate"]["allowed_command_envelope"],
            "clipping_or_rate_limiting": False,
        },
        "physical_stop_gates": {
            "maximum_penetration_m": MAX_PENETRATION_M,
            "maximum_contact_force_n": MAX_CONTACT_FORCE_N,
            "minimum_pelvis_height_m": MIN_PELVIS_HEIGHT_M,
            "minimum_pelvis_up_component": 0.5,
            "finite_state": True,
            "no_external_wrench": True,
            "state_continuity": True,
        },
        "dex3_contract": "independent Source-A hand path; overlay write set excludes hand actuators",
        "rendering": False,
        "training": False,
        "downloads": 0,
        "network": False,
        "production_accepted": False,
        "task_success_claimed": False,
        "bindings": {
            **admission_bindings,
            "source_contract": _binding(source_contract_path),
            "source_a_baseline": _binding(baseline_result_path),
            "runner": _binding(Path(__file__)),
        },
        **source_verification,
    }
    write_json_atomic(output_dir / "PROTOCOL.json", protocol)

    sys.path.insert(0, str(source))
    import mujoco
    import numpy as np
    import onnxruntime as ort

    versions = {
        "mujoco": mujoco.__version__,
        "numpy": np.__version__,
        "onnxruntime": ort.__version__,
    }
    mismatches = {
        key: {"expected": source_contract["environment"].get(key), "actual": value}
        for key, value in versions.items()
        if source_contract["environment"].get(key) != value
    }
    write_json_atomic(
        output_dir / "PREFLIGHT.json",
        {
            "schema": "sonic-bounded-body-physics-smoke-preflight/v1",
            "runtime_versions": versions,
            "expected_versions": source_contract["environment"],
            "runtime_contract_matches": not mismatches,
            "mismatches": mismatches,
            "admission_validated": True,
        },
    )
    if mismatches:
        raise RuntimeError(f"runtime contract mismatch: {mismatches}")

    from ik import pipeline
    from ik import sim

    spec = importlib.util.spec_from_file_location("sonic_body_smoke_sweep", source / "eval/sweep.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the pinned Source-A sweep module")
    sweep = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sweep)
    bounds, nominal = sweep.table_bounds(
        sweep.PRESETS["shipped"].get("cyl_margin_m", 0.045)
    )
    scene = sweep.make_episode(episode_index, seed, "shipped", bounds, nominal)
    kwargs = {
        key: scene[key]
        for key in (
            "spawn",
            "cyl_xy",
            "cyl_mass_scale",
            "cyl_friction",
            "brown_dz",
            "blue_dz",
            "brown_dxy",
            "blue_dxy",
        )
    }
    kwargs["spawn_yaw"] = scene["spawn_yaw_deg"] * np.pi / 180.0
    write_json_atomic(output_dir / "CASE_DRAW.json", json_safe(scene))
    sim.OUT_DIR = output_dir / "native_output"
    sim.OUT_DIR.mkdir(parents=True, exist_ok=True)
    if pipeline.COMMANDER is not None:
        raise RuntimeError("pinned pipeline already has mutable commander state")

    encoder, decoder = _load_onnx_sessions(admission)
    overlay = OnlineSonicActuationOverlay(
        admission=admission,
        encoder=encoder,
        decoder=decoder,
        limits=limits,
        stop=lambda reason: (_ for _ in ()).throw(pipeline.EpisodeAborted(reason)),
    )
    physics_trace: list[dict[str, Any]] = []
    physical = {
        "minimum_pelvis_height_m": float("inf"),
        "minimum_pelvis_up_component": float("inf"),
    }
    counters: NativeCounters | None = None

    def on_step(model: Any, data: Any, step: int, _: Any) -> None:
        quaternion = np.asarray(data.qpos[3:7], dtype=np.float64)
        up = float(1.0 - 2.0 * (quaternion[1] ** 2 + quaternion[2] ** 2))
        pelvis = float(data.qpos[2])
        physical["minimum_pelvis_height_m"] = min(
            physical["minimum_pelvis_height_m"], pelvis
        )
        physical["minimum_pelvis_up_component"] = min(
            physical["minimum_pelvis_up_component"], up
        )
        physics_trace.append(
            {
                "physics_step": step,
                "sim_time_s": float(data.time),
                "pelvis_height_m": pelvis,
                "pelvis_up_component": up,
                "body_command_source": overlay.last_dispatched_source,
            }
        )
        if not (
            np.isfinite(data.qpos).all()
            and np.isfinite(data.qvel).all()
            and np.isfinite(data.ctrl).all()
        ):
            raise pipeline.EpisodeAborted("nonfinite_physical_state")
        if pelvis < MIN_PELVIS_HEIGHT_M:
            raise pipeline.EpisodeAborted("pelvis_height_gate_rejected")
        if up < 0.5:
            raise pipeline.EpisodeAborted("pelvis_upright_gate_rejected")
        if counters is None:
            raise RuntimeError("physics callback ran before counters were bound")
        if counters.max_penetration_m > MAX_PENETRATION_M:
            raise pipeline.EpisodeAborted("penetration_gate_rejected")
        if counters.max_contact_force_n > MAX_CONTACT_FORCE_N:
            raise pipeline.EpisodeAborted("contact_force_gate_rejected")
        if counters.external_wrench_violations:
            raise pipeline.EpisodeAborted("external_wrench_gate_rejected")
        if counters.state_continuity_violations:
            raise pipeline.EpisodeAborted("state_continuity_gate_rejected")

    result: dict[str, Any] = {}
    unexpected_error = None
    # NativeCounters captures the current mj_step in __init__.  Install the
    # actuation overlay first so the counter wraps (rather than bypasses) the
    # final-command guard.
    overlay.install(mujoco)
    counters = NativeCounters(
        mujoco,
        ort,
        max_physics_steps=(limits.maximum_shadow_ticks + limits.maximum_active_ticks + 5)
        * CONTROL_DECIMATION,
        max_sim_seconds=(
            limits.maximum_shadow_ticks + limits.maximum_active_ticks + 5
        )
        / CONTROL_RATE_HZ,
        on_step=on_step,
    )
    counters.install()
    try:
        result = pipeline.run_once(
            **kwargs,
            video=None,
            snapshots=False,
            sim_limit=(
                limits.maximum_shadow_ticks + limits.maximum_active_ticks + 2
            )
            / CONTROL_RATE_HZ,
            wall_limit=120.0,
        )
    except BaseException:
        unexpected_error = traceback.format_exc()
    finally:
        metrics = counters.close()
        overlay.uninstall()
        pipeline.COMMANDER = None

    overlay_report = overlay.report()
    write_json_atomic(
        output_dir / "CONTROL_TRACE.json",
        {
            "schema": "sonic-body-smoke-control-trace/v1",
            "joint_order": list(SONIC_BODY_JOINT_ORDER),
            "rows": overlay.control_trace,
        },
    )
    write_json_atomic(
        output_dir / "PHYSICS_TRACE.json",
        {"schema": "sonic-body-smoke-physics-trace/v1", "rows": physics_trace},
    )
    classification, gates = _classify(
        source_result=result,
        overlay=overlay_report,
        metrics=metrics,
        physical=physical,
        unexpected_error=unexpected_error,
    )
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "physics_smoke_executed": metrics["physics_steps"] > 0,
        "physics_smoke_passed": classification == "passed",
        "candidate_consumed_by_physics": overlay_report["sonic_transmit_ticks"] > 0,
        "actuation_enabled_during_bounded_window": (
            overlay_report["sonic_transmit_ticks"] > 0
        ),
        "gates": gates,
        "stop_reason": result.get("abort"),
        "source_result_boundary": {
            "phase": result.get("phase"),
            "abort": result.get("abort"),
            "error": result.get("error"),
            "sim_time_s": result.get("sim_time_s"),
            "fell": result.get("fell"),
        },
        "overlay": overlay_report,
        "physical": {
            **physical,
            "physics_steps": metrics["physics_steps"],
            "maximum_penetration_m": metrics["max_penetration_m"],
            "maximum_contact_force_n": metrics["max_contact_force_n"],
            "external_wrench_violations": metrics["external_wrench_violations"],
            "state_continuity_violations": metrics["state_continuity_violations"],
            "nonfinite_steps": metrics["nonfinite_steps"],
            "contact_categories": metrics["contact_categories"],
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "physics_steps": metrics["physics_steps"],
            "sonic_model_forwards": overlay_report["model_forwards"],
            "all_onnx_forwards_including_source_a": metrics["policy_forwards"],
            "max_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "wall_seconds": time.monotonic() - started,
        },
        "artifacts": {
            "protocol": _binding(output_dir / "PROTOCOL.json"),
            "preflight": _binding(output_dir / "PREFLIGHT.json"),
            "control_trace": _binding(output_dir / "CONTROL_TRACE.json"),
            "physics_trace": _binding(output_dir / "PHYSICS_TRACE.json"),
        },
        "unexpected_error": unexpected_error,
        "production_accepted": False,
        "task_success_validated": False,
        "grasp_success_validated": False,
        "learning_validated": False,
        "batch_authorized": False,
        "claim_boundary": (
            "A pass proves only one bounded simulator body-control window, command "
            "continuity, basic upright/contact gates, and fail-closed runtime wiring. "
            "It does not prove task, grasp, production, or learning quality."
        ),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output_dir / "RESULT.json", report)
    return report


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
        result = run_smoke(
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
                "schema": "sonic-bounded-body-physics-smoke-runner-failure/v1",
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
                "classification": result["classification"],
                "physics_smoke_passed": result["physics_smoke_passed"],
                "physics_steps": result["physical"]["physics_steps"],
                "shadow_ticks": result["overlay"]["shadow_ticks"],
                "active_ticks": result["overlay"]["active_ticks"],
                "sonic_transmit_ticks": result["overlay"][
                    "sonic_transmit_ticks"
                ],
                "stop_reason": result["stop_reason"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result["classification"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
