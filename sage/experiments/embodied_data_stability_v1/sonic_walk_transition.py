"""Official IDLE-to-WALK reference seam and zero-physics causal diagnostics."""

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


def build_transition_reference(planner, *, speed=0.25, preserve_idle_seam=True):
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
    generated = generate(native.context_from_motion_50hz(idle, generation_frame=2), 2)
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
            native.context_from_motion_50hz(current, generation_frame=52), 2
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
            "mode": 2,
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


def offline_probe(output: Path):
    import numpy as np
    import xml.etree.ElementTree as ET
    from .sonic_playback_shadow import build_reference
    from .audit_sonic_supported_execution import read_bound_json

    if output.exists():
        raise FileExistsError(output)
    source = ROOT / "playing_idle_release_active_01/TRACE.json"
    records = read_bound_json(source)["records"][:100]
    positions = [row["actual_qpos"] for row in records]
    velocities = [row["actual_qvel"] for row in records]
    quaternions = [row["actual_quaternion"] for row in records]
    gyros = [row["actual_gyro"] for row in records]
    # The first ten logged policy observations preceded record zero. Only
    # evaluate ticks >=10, so every decoder history row is actually recorded.
    inputs = native._mapping_inputs(positions, velocities, quaternions, gyros)
    commands = np.asarray(
        [row["actual_command_raw_equivalent_isaaclab"] for row in records],
        dtype=np.float32,
    )
    xml = ET.parse(native.DEFAULT_MODEL).getroot()
    ranges = {
        x.attrib["name"]: tuple(map(float, x.attrib["range"].split()))
        for x in xml.findall(".//joint")
        if "range" in x.attrib
    }
    lower = np.asarray([ranges[x][0] for x in native.SONIC_BODY_JOINT_ORDER])
    upper = np.asarray([ranges[x][1] for x in native.SONIC_BODY_JOINT_ORDER])
    planner = _make_session(
        native.DEFAULT_BUNDLE / "planner/target_vel/V2/planner_sonic.onnx"
    )
    encoder = _make_session(
        native.DEFAULT_BUNDLE / "policy/sonic_v1_1/model_encoder.onnx"
    )
    decoder = _make_session(
        native.DEFAULT_BUNDLE / "policy/sonic_v1_1/model_decoder.onnx"
    )
    variants = []
    for speed in (-1.0, 0.25):
        for seam in (False, True):
            reference, metrics, ref_vel = build_transition_reference(
                planner, speed=speed, preserve_idle_seam=seam
            )
            trace = []
            previous = np.asarray(DEFAULT_ANGLES)
            for tick in range(10, 100):
                enc = ENCODER_ASSEMBLER.assemble(
                    native.build_dynamic_g1_encoder_blocks(
                        reference,
                        ref_vel,
                        tick,
                        initial_robot_quaternion_wxyz=quaternions[0],
                        current_robot_quaternion_wxyz=quaternions[tick],
                    )
                )
                token = encoder.run(
                    None,
                    {encoder.get_inputs()[0].name: np.asarray([enc], dtype=np.float32)},
                )[0]
                dec = DECODER_ASSEMBLER.assemble(
                    official_decoder_blocks(
                        inputs, tick, token, last_action_rows(commands, tick)
                    )
                )
                action = decoder.run(
                    None,
                    {decoder.get_inputs()[0].name: np.asarray([dec], dtype=np.float32)},
                )[0].reshape(29)
                candidate = np.asarray(
                    body_joint_target_from_raw_action(
                        action, phase="offline_walk_probe", sim_time_s=tick * 0.02
                    ).position_target_rad
                )
                guard = guard_candidate(candidate, previous, lower, upper)
                # First comparison is against a missing preceding candidate;
                # exclude it from consecutive-window claims.
                safe = tick > 10 and all(
                    guard[k] for k in ("finite", "in_range", "step_safe")
                )
                trace.append(
                    {
                        "tick": tick,
                        "guard": guard,
                        "safe": safe,
                        "candidate": candidate.tolist(),
                    }
                )
                previous = candidate
            variants.append(
                {
                    "speed": speed,
                    "seam": seam,
                    "planner": metrics,
                    "longest_safe_ticks": native._longest_true_run(
                        [r["safe"] for r in trace]
                    ),
                    "safe_ticks": sum(r["safe"] for r in trace),
                    "trace": trace,
                }
            )
    report = {
        "schema": "sonic-walk-transition-offline-probe/v1",
        "source": _file_binding(source),
        "variants": variants,
        "physics_steps": 0,
        "actuator_writes": 0,
        "admission": False,
        "meaning": "counterfactual reference on recorded real IDLE states; diagnostic only",
        "implementation": _file_binding(Path(__file__)),
    }
    report["content_sha256_excluding_this_field"] = canonical_sha256(report)
    write_json_atomic(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = offline_probe(args.output)
    print(
        json.dumps(
            [
                {k: r[k] for k in ("speed", "seam", "longest_safe_ticks", "safe_ticks")}
                for r in report["variants"]
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
