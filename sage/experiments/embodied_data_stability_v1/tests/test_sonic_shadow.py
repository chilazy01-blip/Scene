import json
import math
from pathlib import Path

import pytest

from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
    BodyJointTarget,
    SonicShadowBridge,
    build_sonic_shadow_preflight,
    inspect_sonic_resources,
)


def target(controller: str, values, *, order=SONIC_BODY_JOINT_ORDER):
    return BodyJointTarget(
        controller_id=controller,
        phase="carry",
        sim_time_s=12.5,
        joint_order=tuple(order),
        position_target_rad=tuple(values),
    )


def test_shadow_comparison_reorders_by_name_and_never_actuates():
    source_values = tuple(float(index) for index in range(29))
    reversed_order = tuple(reversed(SONIC_BODY_JOINT_ORDER))
    sonic_by_name = {
        name: source_values[index] + 0.1
        for index, name in enumerate(SONIC_BODY_JOINT_ORDER)
    }
    sonic_values = tuple(sonic_by_name[name] for name in reversed_order)
    bridge = SonicShadowBridge(SONIC_BODY_JOINT_ORDER)
    row = bridge.compare(
        target("source_a", source_values),
        target("sonic_v1_1", sonic_values, order=reversed_order),
    )
    assert row["candidate_consumed_by_physics"] is False
    assert row["actuation_enabled"] is False
    assert row["metrics"]["max_abs_target_delta_rad"] == pytest.approx(0.1)
    assert row["metrics"]["rms_target_delta_rad"] == pytest.approx(0.1)
    assert not hasattr(bridge, "apply")


def test_shadow_rejects_bad_joint_sets_and_nonfinite_targets():
    bad_order = SONIC_BODY_JOINT_ORDER[:-1] + ("unknown_joint",)
    with pytest.raises(ValueError, match="incompatible"):
        SonicShadowBridge(bad_order)
    values = [0.0] * 29
    values[4] = math.nan
    bridge = SonicShadowBridge(SONIC_BODY_JOINT_ORDER)
    with pytest.raises(ValueError, match="finite"):
        bridge.compare(target("source_a", values), target("sonic", [0.0] * 29))


def test_shadow_rejects_unsynchronised_or_cross_phase_samples():
    values = (0.0,) * 29
    bridge = SonicShadowBridge(SONIC_BODY_JOINT_ORDER)
    late = BodyJointTarget(
        controller_id="sonic",
        phase="carry",
        sim_time_s=12.6,
        joint_order=SONIC_BODY_JOINT_ORDER,
        position_target_rad=values,
    )
    with pytest.raises(ValueError, match="not synchronous"):
        bridge.compare(target("source_a", values), late)
    wrong_phase = BodyJointTarget(
        controller_id="sonic",
        phase="place",
        sim_time_s=12.5,
        joint_order=SONIC_BODY_JOINT_ORDER,
        position_target_rad=values,
    )
    with pytest.raises(ValueError, match="phases differ"):
        bridge.compare(target("source_a", values), wrong_phase)


def test_resource_inspection_does_not_treat_lfs_pointer_as_weight(tmp_path: Path):
    policy = tmp_path / "gear_sonic_deploy" / "policy" / "sonic_v1_1"
    policy.mkdir(parents=True)
    (policy / "model_encoder.onnx").write_text(
        "version https://git-lfs.github.com/spec/v1\n", encoding="utf-8"
    )
    (policy / "model_decoder.onnx").write_bytes(b"real-decoder-bytes")
    (policy / "observation_config.yaml").write_text("observations: []\n")
    report = inspect_sonic_resources(tmp_path)
    assert report["resources"]["encoder"]["state"] == "git_lfs_pointer"
    assert report["resources"]["decoder"]["state"] == "ready"
    assert report["shadow_inference_ready"] is False
    assert report["model_forwards"] == report["physics_steps"] == 0


def test_preflight_accepts_common_joint_set_but_keeps_inference_disabled(tmp_path: Path):
    sonic_contract = tmp_path / "sonic.json"
    source_contract = tmp_path / "source.json"
    sonic_contract.write_text(
        json.dumps(
            {
                "identity": {"repository": "sonic", "commit": "abc"},
                "robot": {
                    "joint_and_actuator_order": {
                        "mjcf_actuator_order": list(SONIC_BODY_JOINT_ORDER)
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    source_contract.write_text(
        json.dumps(
            {
                "identity": {"repository": "source-a", "commit": "def"},
                "action": {
                    "fields_order_units_bounds": {
                        "order": list(SONIC_BODY_JOINT_ORDER)
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    report = build_sonic_shadow_preflight(
        sonic_source_root=tmp_path,
        sonic_contract_path=sonic_contract,
        source_a_contract_path=source_contract,
    )
    assert report["dormant_adapter_ready"] is True
    assert report["joint_mapping"]["exact_order_match"] is True
    assert report["shadow_inference_ready"] is False
    assert report["actuation_enabled"] is False
    assert report["source_a_execution_unchanged"] is True
    assert report["model_forwards"] == report["physics_steps"] == 0
