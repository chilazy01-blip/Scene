import json
from pathlib import Path

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.run_sonic_body_smoke import (
    MAX_ACTIVE_TICKS,
    QUALIFICATION_TICKS,
    RuntimeLimits,
    _classify,
    inverse_target_to_raw_action,
    validate_admission_report,
)
from sage.experiments.embodied_data_stability_v1.run_source_a_native import (
    NativeCounters,
)
from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    scale_action_to_mujoco_targets,
)


def test_runtime_limits_preserve_admitted_budget():
    RuntimeLimits().validate()
    with pytest.raises(ValueError, match="exactly 50"):
        RuntimeLimits(qualification_ticks=49).validate()
    with pytest.raises(ValueError, match=r"\[1,100\]"):
        RuntimeLimits(maximum_active_ticks=101).validate()


def test_inverse_final_target_round_trips_official_action_transform():
    raw = np.linspace(-1.0, 1.0, 29, dtype=np.float64)
    target = scale_action_to_mujoco_targets(raw)
    reconstructed = inverse_target_to_raw_action(target)
    assert np.allclose(reconstructed, raw, atol=1e-12, rtol=0.0)
    assert np.allclose(
        scale_action_to_mujoco_targets(np.zeros(29)), DEFAULT_ANGLES, atol=1e-12
    )


def test_admission_validator_fails_closed_on_false_gate(tmp_path: Path):
    guard = tmp_path / "guard.py"
    shadow = tmp_path / "shadow.py"
    encoder = tmp_path / "encoder.onnx"
    decoder = tmp_path / "decoder.onnx"
    for path in (guard, shadow, encoder, decoder):
        path.write_bytes(path.name.encode())

    def record(path: Path):
        import hashlib

        return {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size_bytes": path.stat().st_size,
        }

    document = {
        "schema": "sonic-causal-takeover-shadow/v1",
        "gates": {
            "full_6209_frame_stream_executed": True,
            "future_data_independence_verified": True,
            "all_outputs_finite": True,
            "one_step_takeover_window_available": True,
            "runtime_guard_bound": True,
            "physics_smoke_admission_ready": False,
        },
        "physics_smoke_contract": {
            "authorized_by_this_report": True,
            "maximum_active_ticks": 100,
            "maximum_active_duration_s": 2.0,
            "start_only_after_runtime_shadow_qualification": True,
            "stop_on_first_guard_rejection": True,
            "dex3_commands_changed": False,
        },
        "runtime_contract": {
            "implementation": record(guard),
            "shadow_qualification_ticks": 50,
            "output_clipping_or_rate_limiting": False,
        },
        "implementation": record(shadow),
        "inputs": {"encoder_model": record(encoder), "decoder_model": record(decoder)},
    }
    report = tmp_path / "admission.json"
    report.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RuntimeError, match="admission gates failed"):
        validate_admission_report(report)


def test_classification_requires_exact_clean_active_budget():
    source = {"abort": "active_tick_budget_complete", "error": None}
    overlay = {
        "consecutive_shadow_passes": QUALIFICATION_TICKS,
        "sonic_transmit_ticks": MAX_ACTIVE_TICKS,
        "active_ticks": MAX_ACTIVE_TICKS,
        "source_a_fallback_transmit_ticks": 0,
        "dex3_write_violations": 0,
    }
    metrics = {
        "nonfinite_steps": 0,
        "external_wrench_violations": 0,
        "state_continuity_violations": 0,
        "max_penetration_m": 0.005,
        "max_contact_force_n": 100.0,
    }
    physical = {
        "minimum_pelvis_height_m": 0.70,
        "minimum_pelvis_up_component": 0.95,
    }
    classification, gates = _classify(
        source_result=source,
        overlay=overlay,
        metrics=metrics,
        physical=physical,
        unexpected_error=None,
    )
    assert classification == "passed"
    assert all(gates.values())

    overlay["sonic_transmit_ticks"] = MAX_ACTIVE_TICKS - 1
    classification, gates = _classify(
        source_result=source,
        overlay=overlay,
        metrics=metrics,
        physical=physical,
        unexpected_error=None,
    )
    assert classification == "diagnostic"
    assert not gates["active_tick_budget_completed"]


def test_counter_must_capture_already_installed_overlay():
    calls = []

    class FakeMujoco:
        @staticmethod
        def mj_step(*_):
            calls.append("real")

    class FakeOrt:
        class InferenceSession:
            @staticmethod
            def run(*_):
                return None

    real = FakeMujoco.mj_step

    def overlay(*args):
        calls.append("overlay")
        return real(*args)

    FakeMujoco.mj_step = overlay
    counters = NativeCounters(FakeMujoco, FakeOrt, 1, 1.0)
    assert counters._old_step is overlay
