from pathlib import Path

import pytest

from sage.experiments.embodied_data_stability_v1.neutral_adapter import (
    DualLayerEpisodeWriter,
    HybridAction,
    TaskInstruction,
    read_policy_episode,
    read_privileged_episode,
)


def instruction() -> TaskInstruction:
    return TaskInstruction(
        task_type="pick_carry_place",
        target_object_semantic_id="light_rigid_object",
        target_support_semantic_id="target_table",
        target_region_semantic_id="clear_drop_region",
        natural_language="Pick up the light object and place it on the target table.",
    )


def action() -> HybridAction:
    return HybridAction(
        phase="approach",
        issued_at_s=0.0,
        valid_for_s=30.0,
        frame_id="world",
        base_pose_xyyaw=(-0.4, 0.1, 0.35),
    )


def test_action_rejects_out_of_envelope_velocity():
    bad = HybridAction(
        phase="carry",
        issued_at_s=1.0,
        valid_for_s=1.0,
        frame_id="base",
        base_velocity_xyyaw=(1.1, 0.0, 0.0),
    )
    with pytest.raises(ValueError):
        bad.validate()


def test_default_reader_cannot_leak_privileged_stream(tmp_path: Path):
    writer = DualLayerEpisodeWriter(tmp_path / "episode", {"episode_id": "smoke-0"})
    writer.append_decision(
        instruction(),
        action(),
        {"task_stage": "approach"},
        {"object_world_pose": [1, 2, 3]},
    )
    writer.finalize()
    policy = read_policy_episode(tmp_path / "episode")
    assert "object_world_pose" not in str(policy)
    with pytest.raises(PermissionError):
        read_privileged_episode(tmp_path / "episode")
    privileged = read_privileged_episode(tmp_path / "episode", explicit=True)
    assert privileged[0]["audit"]["object_world_pose"] == [1, 2, 3]


def test_writer_rejects_privileged_key_in_policy_observation(tmp_path: Path):
    writer = DualLayerEpisodeWriter(tmp_path / "episode", {"episode_id": "smoke-0"})
    with pytest.raises(ValueError):
        writer.append_decision(
            instruction(),
            action(),
            {"contacts": []},
            {"contacts": []},
        )
