"""Event-causal official planner braking; no policy-output shaping.

Each version is a complete global-indexed reference, but is exposed only at
its event. Static hold explicitly repeats the final pose with zero velocity.
"""

from . import sonic_native_dynamic_shadow as native
from .sonic_slow_walk_paced_transition import build_transition_reference as walking


def build_braking_reference(
    planner, *, brake_frame=40, brake_speed=0.15, idle_frame=70, total_frames=350
):
    import numpy as np

    if not 20 <= brake_frame <= 100 or not brake_frame < idle_frame <= 160:
        raise ValueError("braking events outside bounded protocol")
    if brake_speed not in (0.0, 0.1, 0.15, 0.2, 0.25):
        raise ValueError("unadmitted speed command")
    reference, metadata, velocity = walking(planner)
    versions = [(0, reference, velocity)]
    calls = []
    for event, mode, speed in ((brake_frame, 1, brake_speed), (idle_frame, 0, -1.0)):
        context = native.context_from_motion_50hz(reference, generation_frame=event + 2)
        inputs = native.build_planner_inputs(
            context,
            mode=mode,
            target_velocity_m_s=speed,
            movement_direction=(1.0, 0.0, 0.0) if mode else (0.0, 0.0, 0.0),
            random_seed=native.DEFAULT_RANDOM_SEED,
        )
        raw, count, seconds = native._run_once(planner, inputs)
        valid, _, metrics = native.validate_planner_outputs(raw, count)
        generated = native.resample_qpos_50hz(valid)
        merged = native.merge_planner_replan(
            reference, generated, current_frame=event, generation_frame=event + 2
        )
        n = len(merged)
        old_idx = np.clip(np.arange(n) + event, 0, len(reference) - 1)
        new_idx = np.clip(np.arange(n) - 2, 0, len(generated) - 1)
        w = np.clip((np.arange(n) - 2) / 8.0, 0.0, 1.0)[:, None]
        merged_velocity = (1 - w) * velocity[
            old_idx
        ] + w * native._reference_velocities(generated)[new_idx]
        reference = np.concatenate([reference[:event], merged])
        velocity = np.concatenate([velocity[:event], merged_velocity])
        calls.append(
            {
                "event_frame": event,
                "mode": mode,
                "target_speed_m_s": speed,
                "seconds": seconds,
                **metrics,
            }
        )
        versions.append((event, reference, velocity))
    padded = []
    for event, poses, speeds in versions:
        count = max(0, total_frames - len(poses))
        padded.append(
            (
                event,
                np.concatenate([poses, np.repeat(poses[-1:], count, axis=0)]),
                np.concatenate([speeds, np.zeros((count, 29))]),
            )
        )
    metadata.update(
        {
            "brake_command_frame": brake_frame,
            "brake_speed_m_s": brake_speed,
            "stop_command_frame": idle_frame,
            "stop_mode": 0,
            "stop_preview_protocol": "event_causal_brake_then_idle",
            "braking_calls": calls,
            "terminal_hold": "repeat final pose, zero future velocity",
            "version_hashes": [
                {
                    "event": e,
                    "qpos": native._array_sha256(q),
                    "velocity": native._array_sha256(v),
                }
                for e, q, v in padded
            ],
        }
    )
    return padded, metadata


def select_reference(versions, frame):
    selected = versions[0]
    for version in versions:
        if version[0] <= frame:
            selected = version
    return selected[1], selected[2]
