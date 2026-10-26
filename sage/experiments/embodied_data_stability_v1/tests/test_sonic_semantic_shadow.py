import math
from pathlib import Path

import pytest

from sage.experiments.embodied_data_stability_v1.sonic_semantic_shadow import (
    ACTION_SCALES,
    DECODER_ASSEMBLER,
    DECODER_BLOCKS,
    DECODER_DIMENSION,
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    ENCODER_BLOCKS,
    ENCODER_DIMENSION,
    ISAACLAB_TO_MUJOCO,
    action_contract_report,
    body_joint_target_from_raw_action,
    parse_v11_config_order,
    scale_action_to_mujoco_targets,
)
from sage.experiments.embodied_data_stability_v1.sonic_shadow import (
    SONIC_BODY_JOINT_ORDER,
)


def block_values(blocks, fill=0.0):
    return {block.name: [fill] * block.dimension for block in blocks}


def test_frozen_layout_dimensions_and_offsets():
    assert ENCODER_DIMENSION == 1751
    assert DECODER_DIMENSION == 994
    assert ENCODER_ASSEMBLER.layout()[0] == {
        "name": "encoder_mode_4",
        "offset": 0,
        "dimension": 4,
        "end_exclusive": 4,
    }
    assert ENCODER_ASSEMBLER.layout()[-1]["end_exclusive"] == 1751
    assert DECODER_ASSEMBLER.layout()[0]["name"] == "token_state"
    assert DECODER_ASSEMBLER.layout()[-1]["end_exclusive"] == 994


def test_named_assembly_uses_config_order_and_rejects_bad_blocks():
    values = {
        block.name: [float(index + 1)] * block.dimension
        for index, block in enumerate(ENCODER_BLOCKS)
    }
    assembled = ENCODER_ASSEMBLER.assemble(values)
    for index, row in enumerate(ENCODER_ASSEMBLER.layout()):
        assert assembled[row["offset"]] == float(index + 1)
        assert assembled[row["end_exclusive"] - 1] == float(index + 1)

    missing = dict(values)
    missing.pop(ENCODER_BLOCKS[-1].name)
    with pytest.raises(ValueError, match="missing"):
        ENCODER_ASSEMBLER.assemble(missing)
    wrong_dimension = dict(values)
    wrong_dimension[ENCODER_BLOCKS[0].name] = [0.0]
    with pytest.raises(ValueError, match="must contain 4"):
        ENCODER_ASSEMBLER.assemble(wrong_dimension)
    nonfinite = dict(values)
    nonfinite[ENCODER_BLOCKS[0].name] = [0.0, 0.0, math.nan, 0.0]
    with pytest.raises(ValueError, match="finite"):
        ENCODER_ASSEMBLER.assemble(nonfinite)


def test_v11_config_order_parser(tmp_path: Path):
    policy = "\n".join(
        f'  - name: "{block.name}"\n    enabled: true' for block in DECODER_BLOCKS
    )
    encoder = "\n".join(
        f'    - name: "{block.name}"\n      enabled: true' for block in ENCODER_BLOCKS
    )
    path = tmp_path / "observation_config.yaml"
    path.write_text(
        f"observations:\n{policy}\nencoder:\n  dimension: 64\n"
        f"  encoder_observations:\n{encoder}\n  encoder_modes:\n",
        encoding="utf-8",
    )
    report = parse_v11_config_order(path)
    assert report["policy_order_matches"] is True
    assert report["encoder_order_matches"] is True


def test_zero_action_maps_to_defaults_and_basis_mapping_is_one_to_one():
    assert scale_action_to_mujoco_targets([0.0] * 29) == DEFAULT_ANGLES
    report = action_contract_report()
    assert report["all_basis_checks_passed"] is True
    assert len(set(ISAACLAB_TO_MUJOCO)) == 29
    for mujoco_index, isaaclab_index in enumerate(ISAACLAB_TO_MUJOCO):
        raw = [0.0] * 29
        raw[isaaclab_index] = 1.0
        target = scale_action_to_mujoco_targets(raw)
        assert target[mujoco_index] == pytest.approx(
            DEFAULT_ANGLES[mujoco_index] + ACTION_SCALES[mujoco_index]
        )
        assert sum(a != b for a, b in zip(target, DEFAULT_ANGLES)) == 1


def test_action_target_stays_non_actuating_common_joint_contract():
    target = body_joint_target_from_raw_action(
        [0.0] * 29,
        phase="stand",
        sim_time_s=1.0,
    )
    assert target.joint_order == SONIC_BODY_JOINT_ORDER
    assert target.position_target_rad == DEFAULT_ANGLES
    assert target.controller_id == "sonic_v1_1_cpu_shadow"
