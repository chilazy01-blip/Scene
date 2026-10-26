"""Official causal gait, then goal-triggered quintic standing reference."""

import numpy as np
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)
from sage.experiments.embodied_data_stability_v1.sonic_slow_walk_paced_transition import (
    build_transition_reference,
)


def walking(planner):
    # This exact frozen startup has passed. Extend only for full future windows.
    q, meta, v = build_transition_reference(planner)
    while len(q) < 600:
        previous_length = len(q)
        event = len(q) - 50
        inputs = native.build_planner_inputs(
            native.context_from_motion_50hz(q, generation_frame=event + 2),
            mode=1,
            target_velocity_m_s=0.35,
            movement_direction=(1.0, 0.0, 0.0),
            random_seed=1234,
        )
        raw, count, seconds = native._run_once(planner, inputs)
        valid, _, metrics = native.validate_planner_outputs(raw, count)
        new = native.resample_qpos_50hz(valid)
        tail = native.merge_planner_replan(
            q, new, current_frame=event, generation_frame=event + 2
        )
        n = len(tail)
        a = np.clip(np.arange(n) + event, 0, len(q) - 1)
        b = np.clip(np.arange(n) - 2, 0, len(new) - 1)
        weight = np.clip((np.arange(n) - 2) / 8.0, 0.0, 1.0)[:, None]
        tail_v = (1 - weight) * v[a] + weight * native._reference_velocities(new)[b]
        q = np.concatenate([q[:event], tail])
        v = np.concatenate([v[:event], tail_v])
        if len(q) <= previous_length:
            raise RuntimeError("planner reference extension made no forward progress")
        meta["calls"].append({"mode": 1, "seconds": seconds, **metrics})
    meta.update(
        qpos_sha256=native._array_sha256(q),
        velocities_sha256=native._array_sha256(v),
        frame_count_50hz=len(q),
        stop_preview_protocol="measured_goal_triggered_quintic",
    )
    return q, v, meta


def brake(q, v, frame, duration=55):
    stop = min(frame + duration, len(q) - 47)
    target = q[0].copy()
    target[:2] = q[stop, :2]
    target[3:7] = q[frame, 3:7]
    result = q.copy()
    for i in range(frame, len(q)):
        u = min(1.0, (i - frame) / duration)
        weight = u**3 * (10 + u * (-15 + 6 * u))
        result[i, :3] = (1 - weight) * q[i, :3] + weight * target[:3]
        result[i, 3:7] = native._quaternion_slerp(q[i, 3:7], target[3:7], weight)
        result[i, 7:] = (1 - weight) * q[i, 7:] + weight * target[7:]
    velocity = native._reference_velocities(result)
    velocity[stop:] = 0
    return result, velocity, stop


class GoalClock:
    def __init__(self, case):
        self.case = case
        self.event = None
        self.stop = None
        self.q = None
        self.v = None

    def update(self, q, v, frame, root, velocity):
        yaw = self.case["start_yaw_rad"]
        direction = np.array([np.cos(yaw), np.sin(yaw)])
        delta = np.asarray(root[:2]) - self.case["start_xy_m"]
        progress = float(delta @ direction)
        speed = max(0.0, float(np.asarray(velocity[:2]) @ direction))
        # Causal distance-to-go plus stopping-distance estimate, not a fixed tick.
        stopping_distance = 0.16  # fixed before pilots; not fitted per episode
        if (
            self.event is None
            and frame >= 75
            and progress >= self.case["goal_distance_m"] - stopping_distance
        ):
            self.event = frame
            self.q, self.v, self.stop = brake(q, v, frame)
        return (self.q, self.v) if self.event is not None else (q, v)
