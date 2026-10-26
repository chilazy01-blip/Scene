import json

import numpy as np
import pytest

from sage.experiments.embodied_data_stability_v1 import (
    sonic_playback_shadow as playback,
)


@pytest.mark.parametrize("mode, expected_calls", [(0, 4), (2, 5)])
def test_planner_extension_covers_complete_active_future_window(
    monkeypatch, mode, expected_calls
):
    calls = []

    def run_once(session, inputs):
        calls.append(inputs["mode"].item())
        qpos = np.zeros((1, 64, 36), dtype=np.float32)
        qpos[:, :, 2] = 0.79
        qpos[:, :, 3] = 1.0
        qpos[0, :, 7:] = np.arange(64)[:, None] * 0.001 + len(calls) * 0.01
        return qpos, np.array([44], dtype=np.int64), 0.01

    monkeypatch.setattr(playback.native, "_run_once", run_once)
    qpos, metrics, velocity = playback.build_reference(object(), mode)
    assert len(calls) == expected_calls
    assert qpos.shape == (225, 36)
    assert velocity.shape == (225, 29)
    assert len(qpos) >= 150 + playback.native.G1_LOOKAHEAD_TICKS
    assert np.isfinite(qpos).all() and np.isfinite(velocity).all()
    assert metrics["mode"] == mode
    assert len(metrics["calls"]) == expected_calls


def test_paused_startup_success_does_not_admit_playing_reference(tmp_path):
    report = {
        "schema": "sonic-supported-shadow/v1",
        "classification": "passed",
        "sonic_only_physics_smoke_admission_ready": True,
        "reference_playing": False,
    }
    report["content_sha256_excluding_this_field"] = playback.canonical_sha256(report)
    path = tmp_path / "paused.json"
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError, match="playing-reference configuration"):
        playback.validated_admission(path)


def test_playing_admission_rejects_tampered_hash(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"content_sha256_excluding_this_field": "invalid"}))
    with pytest.raises(RuntimeError, match="hash mismatch"):
        playback.validated_admission(path)


def test_official_support_off_clears_wrench_before_next_step():
    mujoco = pytest.importorskip("mujoco")
    xml, _ = playback.native.stripped_official_model_xml(playback.native.DEFAULT_MODEL)
    model = mujoco.MjModel.from_xml_string(xml.decode())
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    body = model.body("pelvis").id
    band = playback.load_official_band()
    supported = playback.apply_official_band(mujoco, model, data, band, body)
    assert np.any(supported)
    band.handle_keyboard_button("9")
    released = playback.apply_official_band(mujoco, model, data, band, body)
    assert band.enable is False
    assert not np.any(released) and not np.any(data.xfrc_applied)


def test_support_schedule_change_rejected_before_creating_run(monkeypatch, tmp_path):
    pytest.importorskip("mujoco")
    monkeypatch.setattr(
        playback,
        "validated_admission",
        lambda path: {"report": {"support": {"release_on_active": False}}},
    )
    output = tmp_path / "must_not_start"
    with pytest.raises(RuntimeError, match="support schedule"):
        playback.run_shadow(
            output,
            active_admission=tmp_path / "admission.json",
            release_support_on_active=True,
        )
    assert not output.exists()
