"""Causal C2 WALK-to-standing reference synthesis, not raw-action shaping.

Uses a real official IDLE target and the already generated walking trajectory.
After an announced brake event only, a quintic blend cancels future steps and
settles into a symmetric standing pose. Position and velocity are consistent.
This is an engineered task reference, NOT an official planner IDLE replan.
"""

from . import sonic_native_dynamic_shadow as native
from .sonic_slow_walk_paced_transition import build_transition_reference as walking
from .sonic_braking_reference import select_reference


def build_braking_reference(
    planner, *, brake_frame=75, brake_speed=0.25, idle_frame=130, total_frames=350
):
    import numpy as np

    if brake_speed != 0.25 or (brake_frame, idle_frame) not in ((75, 130), (40, 105)):
        raise ValueError("only declared C2 reference profiles")
    original, metadata, original_velocity = walking(planner)
    n = max(total_frames, len(original))
    reference = np.concatenate(
        [original, np.repeat(original[-1:], n - len(original), axis=0)]
    )
    velocity = np.concatenate([original_velocity, np.zeros((n - len(original), 29))])
    standing = reference[0].copy()
    standing[:2] = reference[idle_frame, :2]
    standing[3:7] = reference[brake_frame, 3:7]
    brake = reference.copy()
    for frame in range(brake_frame, n):
        u = min(1.0, (frame - brake_frame) / (idle_frame - brake_frame))
        weight = u * u * u * (10 + u * (-15 + 6 * u))
        brake[frame, :3] = (1 - weight) * reference[frame, :3] + weight * standing[:3]
        brake[frame, 3:7] = native._quaternion_slerp(
            reference[frame, 3:7], standing[3:7], weight
        )
        brake[frame, 7:] = (1 - weight) * reference[frame, 7:] + weight * standing[7:]
    brake_velocity = native._reference_velocities(brake)
    brake_velocity[idle_frame:] = 0.0
    versions = [(0, reference, velocity), (brake_frame, brake, brake_velocity)]
    metadata.update(
        {
            "brake_command_frame": brake_frame,
            "brake_speed_m_s": brake_speed,
            "brake_speed_parameter_semantics": "compatibility profile identifier; not a planner velocity input",
            "stop_command_frame": idle_frame,
            "stop_mode": 0,
            "stop_preview_protocol": "event_causal_brake_then_idle",
            "braking_method": "engineered quintic pose blend; planner walking and official initial IDLE target",
            "terminal_hold": "fixed official IDLE pose and zero reference velocity",
            "version_hashes": [
                {
                    "event": e,
                    "qpos": native._array_sha256(q),
                    "velocity": native._array_sha256(v),
                }
                for e, q, v in versions
            ],
        }
    )
    return versions, metadata
