"""Fixed 0.6s SLOW_WALK -> official IDLE command, with native cross-fades."""

from . import sonic_native_dynamic_shadow as native

STOP_COMMAND_FRAME = 30


def build_transition_reference(planner, *, speed=0.35, preserve_idle_seam=True):
    import numpy as np

    if speed != 0.35 or not preserve_idle_seam:
        raise ValueError("fixed walk-stop protocol only")
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
        calls.append({"mode": mode, "seconds": seconds, **metrics})
        return native.resample_qpos_50hz(valid)

    def merge(old, old_vel, new, consumed):
        count = 2 + len(new)
        old_idx = np.clip(np.arange(count) + consumed, 0, len(old) - 1)
        new_idx = np.clip(np.arange(count) - 2, 0, len(new) - 1)
        weight = np.clip((np.arange(count) - 2) / 8.0, 0.0, 1.0)[:, None]
        vel = (1 - weight) * old_vel[old_idx] + weight * native._reference_velocities(
            new
        )[new_idx]
        return (
            native.merge_planner_replan(
                old, new, current_frame=consumed, generation_frame=consumed + 2
            ),
            vel,
        )

    idle = generate(native.initialize_context(), 0)
    walk = generate(native.context_from_motion_50hz(idle, generation_frame=2), 1)
    current, velocity = merge(idle, native._reference_velocities(idle), walk, 0)
    chunks, velocities = [], []
    for consumed in (STOP_COMMAND_FRAME, 50, 50):
        stopped = generate(
            native.context_from_motion_50hz(current, generation_frame=consumed + 2), 0
        )
        chunks.append(current[:consumed].copy())
        velocities.append(velocity[:consumed].copy())
        current, velocity = merge(current, velocity, stopped, consumed)
    reference = np.concatenate([*chunks, current])
    velocities = np.concatenate([*velocities, velocity])
    return (
        reference,
        {
            "mode": 1,
            "target_speed_m_s": speed,
            "stop_mode": 0,
            "stop_command_frame": STOP_COMMAND_FRAME,
            "stop_command_time_s": STOP_COMMAND_FRAME * 0.02,
            "schedule": "IDLE -> SLOW_WALK(0.35m/s) -> IDLE at fixed 0.6s",
            "future_command_preview": "fixed schedule known from start; official 45-tick lookahead",
            "calls": calls,
            "frame_count_50hz": len(reference),
            "qpos_sha256": native._array_sha256(reference),
            "velocities_sha256": native._array_sha256(velocities),
        },
        velocities,
    )
