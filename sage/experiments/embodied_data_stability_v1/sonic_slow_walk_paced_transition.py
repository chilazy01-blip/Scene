"""Official IDLE-to-SLOW_WALK reference seam with the learned default speed."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import sonic_native_dynamic_shadow as native
from .audit_candidates import canonical_sha256, write_json_atomic
from .sonic_native_full_shadow import _make_session
from .sonic_native_planner_preflight import _file_binding
from .sonic_semantic_shadow import (
    DEFAULT_ANGLES,
    ENCODER_ASSEMBLER,
    DECODER_ASSEMBLER,
    body_joint_target_from_raw_action,
)
from .sonic_supported_shadow import (
    official_decoder_blocks,
    last_action_rows,
    guard_candidate,
)
from .sonic_offline_observation_mapper import reorder_mujoco_to_isaaclab

ROOT = native.DEFAULT_RUN_ROOT


def build_transition_reference(planner, *, speed=0.35, preserve_idle_seam=True):
    import numpy as np

    calls = []

    def generate(context, mode):
        inputs = native.build_planner_inputs(
            context,
            mode=mode,
            target_velocity_m_s=speed if mode else -1.0,
            movement_direction=(1.0, 0.0, 0.0) if mode else (0.0, 0.0, 0.0),
            random_seed=native.DEFAULT_RANDOM_SEED,
        )
        raw, count, seconds = native._run_once(planner, inputs)
        valid, _, metrics = native.validate_planner_outputs(raw, count)
        calls.append(
            {
                "mode": mode,
                "target_speed_m_s": speed if mode else -1.0,
                "seconds": seconds,
                **metrics,
            }
        )
        return native.resample_qpos_50hz(valid)

    idle = generate(native.initialize_context(), 0)
    generated = generate(native.context_from_motion_50hz(idle, generation_frame=2), 1)
    if preserve_idle_seam:
        current = native.merge_planner_replan(
            idle, generated, current_frame=0, generation_frame=2
        )
        old_velocity = native._reference_velocities(idle)
        new_velocity = native._reference_velocities(generated)
        count = len(current)
        old_idx = np.clip(np.arange(count), 0, len(idle) - 1)
        new_idx = np.clip(np.arange(count) - 2, 0, len(generated) - 1)
        w = np.clip((np.arange(count) - 2) / 8.0, 0.0, 1.0)[:, None]
        velocity = (1 - w) * old_velocity[old_idx] + w * new_velocity[new_idx]
    else:
        current, velocity = generated, native._reference_velocities(generated)
    chunks, velocity_chunks = [], []
    for _ in range(3):
        generated = generate(
            native.context_from_motion_50hz(current, generation_frame=52), 1
        )
        new_velocity = native._reference_velocities(generated)
        chunks.append(current[:50].copy())
        velocity_chunks.append(velocity[:50].copy())
        count = 2 + len(generated)
        old_idx = np.clip(np.arange(count) + 50, 0, len(current) - 1)
        new_idx = np.clip(np.arange(count) - 2, 0, len(generated) - 1)
        w = np.clip((np.arange(count) - 2) / 8.0, 0.0, 1.0)[:, None]
        velocity = (1 - w) * velocity[old_idx] + w * new_velocity[new_idx]
        current = native.merge_planner_replan(
            current, generated, current_frame=50, generation_frame=52
        )
    reference = np.concatenate([*chunks, current])
    velocities = np.concatenate([*velocity_chunks, velocity])
    return (
        reference,
        {
            "mode": 1,
            "calls": calls,
            "target_speed_m_s": speed,
            "preserve_official_idle_seam": preserve_idle_seam,
            "qpos_sha256": native._array_sha256(reference),
            "velocities_sha256": native._array_sha256(velocities),
            "frame_count_50hz": len(reference),
            "horizontal_displacement_m": float(
                np.linalg.norm(reference[-1, :2] - reference[0, :2])
            ),
        },
        velocities,
    )
