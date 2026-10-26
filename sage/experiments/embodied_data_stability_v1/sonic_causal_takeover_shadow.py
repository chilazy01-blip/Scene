"""Run the full causal SONIC one-step takeover screen without physics."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_causal_hold_shadow import _prefix
from .sonic_causal_reference_diagnostic import (
    TAKEOVER_QUALIFICATION_TICKS,
    VARIANTS,
    build_causal_measured_state_hold_encoder_blocks,
    build_source_applied_action_history,
    build_source_non_regression_gate,
    inspect_source_a_reference_capability,
    run_variant,
)
from .sonic_offline_observation_mapper import (
    CONTROL_DT_S,
    DEFAULT_S3_EPISODE,
    DEFAULT_SONIC_RUN,
    DEFAULT_SOURCE_A,
    _file_binding,
    build_decoder_blocks,
    load_mapping_inputs,
)
from .sonic_runtime_guard import SonicRuntimeGuard
from .sonic_semantic_shadow import DECODER_ASSEMBLER, ENCODER_ASSEMBLER


SCHEMA = "sonic-causal-takeover-shadow/v1"
CANDIDATE_NAME = "causal_measured_state_hold_source_applied_history"
DEFAULT_OUTPUT = DEFAULT_SONIC_RUN / "SONIC_CAUSAL_TAKEOVER_SHADOW.json"
PREFIX_PROBE_CANDIDATES = (0, 1, 9, 10, 321, 386, 1000)


def verify_takeover_prefix_equivalence(inputs: Any) -> dict[str, Any]:
    """Compare full-stream observations to physically truncated input prefixes."""

    import numpy as np

    indices = sorted(
        {
            *(
                index
                for index in PREFIX_PROBE_CANDIDATES
                if 0 <= index < inputs.sample_count
            ),
            inputs.sample_count - 1,
        }
    )
    token = np.arange(64, dtype=np.float64) * 0.01
    rows = []
    all_equal = True
    for index in indices:
        prefix = _prefix(inputs, index + 1)
        full_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(
                build_causal_measured_state_hold_encoder_blocks(inputs, index)
            ),
            dtype=np.float32,
        )
        prefix_encoder = np.asarray(
            ENCODER_ASSEMBLER.assemble(
                build_causal_measured_state_hold_encoder_blocks(prefix, index)
            ),
            dtype=np.float32,
        )
        full_history = build_source_applied_action_history(inputs, index + 1)
        prefix_history = build_source_applied_action_history(prefix, index + 1)
        full_decoder = np.asarray(
            DECODER_ASSEMBLER.assemble(
                build_decoder_blocks(
                    inputs,
                    index,
                    token_state=token,
                    logged_last_actions_isaaclab=full_history,
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
                    logged_last_actions_isaaclab=prefix_history,
                )
            ),
            dtype=np.float32,
        )
        encoder_equal = bool(np.array_equal(full_encoder, prefix_encoder))
        history_equal = bool(np.array_equal(full_history, prefix_history))
        decoder_equal = bool(np.array_equal(full_decoder, prefix_decoder))
        all_equal = all_equal and encoder_equal and history_equal and decoder_equal
        rows.append(
            {
                "sample_index": index,
                "prefix_sample_count": index + 1,
                "encoder_equal": encoder_equal,
                "source_applied_action_history_equal": history_equal,
                "decoder_equal": decoder_equal,
                "encoder_sha256": hashlib.sha256(full_encoder.tobytes()).hexdigest(),
                "decoder_sha256": hashlib.sha256(full_decoder.tobytes()).hexdigest(),
            }
        )
    return {
        "method": "full_stream_vs_physically_truncated_prefix_exact_float32_equality",
        "probe_count": len(rows),
        "maximum_future_row_offset": 0,
        "all_equal": all_equal,
        "probes": rows,
    }


def _runtime_contract(gate: dict[str, Any], guard_path: Path) -> dict[str, Any]:
    envelope = gate["allowed_command_envelope"]
    # Construction is an executable validation of the frozen guard parameters.
    SonicRuntimeGuard(
        lower_rad=envelope["admission_lower_rad"],
        upper_rad=envelope["admission_upper_rad"],
        max_abs_delta_rad=gate["allowed_global_max_abs_delta_rad"],
        qualification_ticks=TAKEOVER_QUALIFICATION_TICKS,
    )
    return {
        "implementation": _file_binding(guard_path),
        "control_rate_hz": int(round(1.0 / CONTROL_DT_S)),
        "shadow_qualification_ticks": TAKEOVER_QUALIFICATION_TICKS,
        "shadow_qualification_s": TAKEOVER_QUALIFICATION_TICKS * CONTROL_DT_S,
        "handoff_checks": [
            "complete 29-joint proposal is finite",
            "complete proposal is inside the frozen model-or-Source-A envelope",
            "maximum delta from the previously dispatched command does not exceed the frozen 50 Hz limit",
        ],
        "active_checks_repeat_every_tick": True,
        "output_clipping_or_rate_limiting": False,
        "candidate_failure": (
            "Never dispatch the failing SONIC proposal. Latch to Source A only if "
            "that complete fallback command independently passes the same envelope "
            "and slew checks; otherwise emit no command and stop the smoke runner."
        ),
        "fallback_is_latched": True,
        "reentry_after_failure": "new process and a new full shadow qualification",
        "rollback": (
            "SONIC remains an optional side path; Source A files and controller state "
            "are not modified by qualification or by a rejected handoff."
        ),
        "dex3_contract": "Dex3 remains on its existing independent external controller.",
    }


def run_full_takeover_shadow(
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
    gate = build_source_non_regression_gate(inputs, source_a_root)
    prefix_proof = verify_takeover_prefix_equivalence(inputs)
    source_capability = inspect_source_a_reference_capability(source_a_root)
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
    spec = next(row for row in VARIANTS if row["name"] == CANDIDATE_NAME)
    candidate = run_variant(
        spec=spec,
        inputs=inputs,
        encoder=encoder,
        decoder=decoder,
        sample_count=inputs.sample_count,
        gate=gate,
    )
    takeover = candidate["one_step_takeover_screen"]
    runtime_contract = _runtime_contract(
        gate, Path(__file__).with_name("sonic_runtime_guard.py")
    )
    admission_ready = bool(
        prefix_proof["all_equal"]
        and candidate["all_outputs_finite"]
        and takeover["passed"]
        and takeover["qualifying_window_count"] > 0
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
        "frozen_gate": gate,
        "causality_proof": prefix_proof,
        "candidate": candidate,
        "runtime_contract": runtime_contract,
        "physics_smoke_contract": {
            "authorized_by_this_report": admission_ready,
            "scope": "simulator-only body-control smoke; not production or task success",
            "maximum_active_ticks": 100,
            "maximum_active_duration_s": 100 * CONTROL_DT_S,
            "start_only_after_runtime_shadow_qualification": True,
            "stop_on_first_guard_rejection": True,
            "dex3_commands_changed": False,
            "object_or_grasp_success_claimed": False,
        },
        "gates": {
            "full_6209_frame_stream_executed": inputs.sample_count == 6209,
            "future_data_independence_verified": prefix_proof["all_equal"],
            "all_outputs_finite": candidate["all_outputs_finite"],
            "one_step_takeover_window_available": takeover["passed"],
            "runtime_guard_bound": True,
            "physics_smoke_admission_ready": admission_ready,
            "physics_executed": False,
            "actuation_enabled": False,
            "candidate_consumed_by_physics": False,
            "production_accepted": False,
            "task_success_validated": False,
        },
        "audit_scope": {
            "network_accessed": False,
            "downloads": 0,
            "model_forwards": candidate["model_forwards"],
            "physics_steps": 0,
            "rendered_frames": 0,
            "training_steps": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "claim_boundary": (
            "The full stream contains independent causal one-step takeover proposals "
            "on frozen Source-A states. It proves safe handoff windows under the frozen "
            "gate, not SONIC closed-loop stability. Closed-loop evidence begins only in "
            "the separately bounded simulator smoke under the fail-closed guard."
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
    report = run_full_takeover_shadow(
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
