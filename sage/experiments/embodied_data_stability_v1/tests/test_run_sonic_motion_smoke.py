import json
from pathlib import Path

import pytest

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    canonical_sha256,
)
from sage.experiments.embodied_data_stability_v1.run_sonic_body_smoke import (
    MAX_ACTIVE_TICKS,
    QUALIFICATION_TICKS,
)
from sage.experiments.embodied_data_stability_v1.run_sonic_motion_smoke import (
    MAXIMUM_SHADOW_TICKS,
    MotionRuntimeLimits,
    _motion_classify,
    validate_motion_admission_report,
)


def test_motion_runtime_limits_are_fixed():
    MotionRuntimeLimits().validate()
    with pytest.raises(ValueError, match="600"):
        MotionRuntimeLimits(maximum_shadow_ticks=599).validate()
    with pytest.raises(ValueError, match="100"):
        MotionRuntimeLimits(maximum_active_ticks=99).validate()
    assert MAXIMUM_SHADOW_TICKS == 600


def _record(path: Path):
    import hashlib

    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def test_motion_admission_validator_binds_content_and_runtime(tmp_path: Path):
    files = {}
    for name in ("reference.py", "guard.py", "encoder.onnx", "decoder.onnx"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        files[name] = path
    document = {
        "schema": "sonic-causal-motion-reference-shadow/v1",
        "implementation": _record(files["reference.py"]),
        "inputs": {
            "encoder_model": _record(files["encoder.onnx"]),
            "decoder_model": _record(files["decoder.onnx"]),
        },
        "gates": {
            "full_6209_reference_stream_built": True,
            "future_data_independence_verified": True,
            "task_conditioned_0_9s_29_joint_reference_ready": True,
            "prediction_not_worse_than_hold_on_frozen_scopes": True,
            "reference_integrity_passed": True,
            "full_cpu_shadow_executed": True,
            "all_sonic_outputs_finite": True,
            "one_step_takeover_window_available": True,
            "motion_bearing_takeover_window_available": True,
            "runtime_guard_bound": True,
            "motion_physics_smoke_admission_ready": True,
        },
        "runtime_contract": {
            "implementation": _record(files["guard.py"]),
            "shadow_qualification_ticks": 50,
            "maximum_active_ticks": 100,
            "maximum_active_duration_s": 2.0,
            "qualification_requires_motion_bearing_reference": True,
            "active_checks_repeat_every_tick": True,
            "output_clipping_or_rate_limiting": False,
            "dex3_commands_changed": False,
        },
    }
    document["content_sha256_excluding_this_field"] = canonical_sha256(document)
    report_path = tmp_path / "admission.json"
    report_path.write_text(json.dumps(document), encoding="utf-8")
    report, bindings = validate_motion_admission_report(report_path)
    assert report["gates"]["motion_physics_smoke_admission_ready"]
    assert bindings["runtime_guard"]["path"] == str(files["guard.py"])

    broken = json.loads(report_path.read_text(encoding="utf-8"))
    broken["gates"]["motion_bearing_takeover_window_available"] = False
    report_path.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(RuntimeError, match="content hash mismatch"):
        validate_motion_admission_report(report_path)


def test_motion_classification_requires_motion_on_every_sonic_tick():
    source = {"abort": "active_tick_budget_complete", "error": None}
    overlay = {
        "consecutive_shadow_passes": QUALIFICATION_TICKS,
        "maximum_consecutive_motion_shadow_passes": QUALIFICATION_TICKS,
        "sonic_transmit_ticks": MAX_ACTIVE_TICKS,
        "active_motion_reference_ticks": MAX_ACTIVE_TICKS,
        "active_ticks": MAX_ACTIVE_TICKS,
        "source_a_fallback_transmit_ticks": 0,
        "dex3_write_violations": 0,
        "minimum_active_reference_displacement_rad": 0.03,
    }
    metrics = {
        "nonfinite_steps": 0,
        "external_wrench_violations": 0,
        "state_continuity_violations": 0,
        "max_penetration_m": 0.005,
        "max_contact_force_n": 100.0,
        "active_physics_steps": MAX_ACTIVE_TICKS * 4,
    }
    physical = {
        "minimum_pelvis_height_m": 0.70,
        "minimum_pelvis_up_component": 0.95,
    }
    classification, gates = _motion_classify(
        source_result=source,
        overlay=overlay,
        metrics=metrics,
        physical=physical,
        unexpected_error=None,
    )
    assert classification == "passed"
    assert all(gates.values())
    overlay["active_motion_reference_ticks"] -= 1
    classification, gates = _motion_classify(
        source_result=source,
        overlay=overlay,
        metrics=metrics,
        physical=physical,
        unexpected_error=None,
    )
    assert classification == "diagnostic"
    assert not gates["motion_reference_present_on_every_sonic_tick"]
