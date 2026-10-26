from dataclasses import replace

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1.sonic_base_translation_admission import (
    screen_base_translation_takeover,
)
from sage.experiments.embodied_data_stability_v1.sonic_causal_motion_reference import (
    build_causal_reference_stream,
)
from sage.experiments.embodied_data_stability_v1.tests.test_sonic_causal_motion_reference import (
    fake_inputs,
)


def _moving_reference_and_gate(rows: int):
    inputs = fake_inputs(rows)
    reference = build_causal_reference_stream(
        inputs, np.zeros(rows, dtype=np.int64)
    )
    positions = reference.positions_mujoco_rad.copy()
    positions[:, -1, 0] += 0.1
    reference = replace(
        reference,
        positions_mujoco_rad=positions,
        analog_available=np.ones(rows, dtype=bool),
    )
    gate = {
        "allowed_global_max_abs_delta_rad": 1.0,
        "allowed_command_envelope": {
            "admission_lower_rad": [-10.0] * 29,
            "admission_upper_rad": [10.0] * 29,
        },
    }
    return inputs, reference, gate


def test_translation_screen_admits_only_after_full_speed_qualification():
    inputs, reference, gate = _moving_reference_and_gate(80)
    velocity = np.zeros((80, 6), dtype=np.float64)
    velocity[:, 0] = 0.1
    position = np.zeros((80, 2), dtype=np.float64)
    position[:, 0] = np.arange(80) * 0.002
    report = screen_base_translation_takeover(
        targets=np.zeros((80, 29), dtype=np.float64),
        inputs=inputs,
        reference=reference,
        gate=gate,
        base_velocity_m_s=velocity,
        base_position_xy_m=position,
    )
    assert report["passed"]
    selected = report["selected_threshold"]
    assert selected["longest_eligible_run_ticks"] == 79
    assert selected["qualifying_window_count"] == 1
    assert selected["stage_intersections"]["base_translation_only"][
        "longest_run_ticks"
    ] == 79
    assert selected["stage_intersections"]["plus_handoff_and_envelope"][
        "longest_run_ticks"
    ] == 79
    assert selected["longest_eligible_run"][
        "actual_net_horizontal_displacement_m"
    ] == pytest.approx(0.156)


def test_translation_screen_rejects_a_49_tick_short_window():
    inputs, reference, gate = _moving_reference_and_gate(80)
    velocity = np.zeros((80, 6), dtype=np.float64)
    velocity[1:50, 0] = 0.1
    report = screen_base_translation_takeover(
        targets=np.zeros((80, 29), dtype=np.float64),
        inputs=inputs,
        reference=reference,
        gate=gate,
        base_velocity_m_s=velocity,
        base_position_xy_m=np.zeros((80, 2), dtype=np.float64),
    )
    assert not report["passed"]
    assert report["selected_threshold"]["longest_eligible_run_ticks"] == 49
    assert report["selected_threshold"]["qualifying_window_count"] == 0


def test_privileged_position_changes_audit_but_not_eligibility():
    inputs, reference, gate = _moving_reference_and_gate(80)
    velocity = np.zeros((80, 6), dtype=np.float64)
    velocity[:, 0] = 0.1
    first = screen_base_translation_takeover(
        targets=np.zeros((80, 29), dtype=np.float64),
        inputs=inputs,
        reference=reference,
        gate=gate,
        base_velocity_m_s=velocity,
        base_position_xy_m=np.zeros((80, 2), dtype=np.float64),
    )
    changed_position = np.zeros((80, 2), dtype=np.float64)
    changed_position[:, 0] = np.arange(80)
    second = screen_base_translation_takeover(
        targets=np.zeros((80, 29), dtype=np.float64),
        inputs=inputs,
        reference=reference,
        gate=gate,
        base_velocity_m_s=velocity,
        base_position_xy_m=changed_position,
    )
    assert first["selected_threshold"]["eligible_sample_count"] == second[
        "selected_threshold"
    ]["eligible_sample_count"]
    assert first["selected_threshold"]["qualifying_window_count"] == second[
        "selected_threshold"
    ]["qualifying_window_count"]
    assert first["selected_threshold"]["longest_eligible_run"][
        "actual_net_horizontal_displacement_m"
    ] != second["selected_threshold"]["longest_eligible_run"][
        "actual_net_horizontal_displacement_m"
    ]


def test_translation_screen_fails_closed_on_nonfinite_velocity():
    inputs, reference, gate = _moving_reference_and_gate(80)
    velocity = np.zeros((80, 6), dtype=np.float64)
    velocity[10, 0] = np.nan
    with pytest.raises(ValueError, match="must be finite"):
        screen_base_translation_takeover(
            targets=np.zeros((80, 29), dtype=np.float64),
            inputs=inputs,
            reference=reference,
            gate=gate,
            base_velocity_m_s=velocity,
            base_position_xy_m=np.zeros((80, 2), dtype=np.float64),
        )
