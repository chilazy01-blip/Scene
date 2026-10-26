"""Causal quiet stand, original learned gait, measured-goal brake and quiet hold."""

import math
import numpy as np
from sage.experiments.embodied_locomotion_v1.reference import brake
from sage.experiments.embodied_native_walk_v1.acceptance_v1 import _stand, LIMITS


class Clock:
    def __init__(self, q, v, case, brake_ticks=55):
        self.base_q = q
        self.base_v = v
        self.case = case
        self.brake_ticks = brake_ticks
        self.idle_q = np.repeat(q[:1], len(q), axis=0)
        self.idle_v = np.zeros_like(v)
        self.q = self.idle_q
        self.v = self.idle_v
        self.phase = "initial_stand"
        self.walk_start = None
        self.brake_frame = None
        self.brake_tick = None
        self.final_tick = None
        self.events = []
        self.failure = None
        self.done = False
        self.walk_origin = None
        yaw = math.radians(case["start_yaw_deg"])
        self.direction = np.array([math.cos(yaw), math.sin(yaw)])

    def change(self, phase, tick, data):
        self.phase = phase
        self.events.append(
            {
                "phase": phase,
                "active_tick": tick,
                "simulator_time_s": float(data.time),
                "actual_root_m": data.qpos[:3].tolist(),
            }
        )

    def update(self, tick, data, measurements):
        if self.phase == "initial_stand":
            if (
                tick >= 500
                and _stand(
                    [s for s in measurements if s["phase"] == "initial_stand"], 10.0
                )["passed"]
            ):
                self.walk_start = tick
                self.walk_origin = data.qpos[:2].copy()
                self.q = self.base_q
                self.v = self.base_v
                self.change("walking", tick, data)
            elif tick >= 750:
                self.failure = "initial_stand_timeout"
        frame = (
            0
            if self.walk_start is None
            else min(tick - self.walk_start, len(self.q) - 46)
        )
        if self.phase == "walking":
            progress = float(
                (data.qpos[:2] - np.asarray(self.case["start_xy_m"])) @ self.direction
            )
            if frame >= 75 and progress >= 1.15 - 0.16:
                self.q, self.v, stop = brake(
                    self.base_q, self.base_v, frame, duration=self.brake_ticks
                )
                self.brake_frame = stop
                self.brake_tick = tick
                self.change("braking", tick, data)
            elif tick - self.walk_start >= 500:
                self.failure = "walking_goal_timeout"
        if self.phase == "braking":
            speed = float(np.linalg.norm(data.qvel[:3]))
            error = float(
                np.linalg.norm(data.qpos[:2] - np.asarray(self.case["goal_xy_m"]))
            )
            forward = float((data.qpos[:2] - self.walk_origin) @ self.direction)
            if (
                frame >= self.brake_frame
                and speed <= 0.04
                and error <= 0.15
                and forward >= 1.0
            ):
                self.final_tick = tick
                self.change("final_stand", tick, data)
            elif tick - self.brake_tick >= 300:
                self.failure = "braking_or_destination_timeout"
        if self.phase == "final_stand":
            if (
                tick - self.final_tick >= 250
                and _stand(
                    [s for s in measurements if s["phase"] == "final_stand"], 5.0
                )["passed"]
            ):
                self.done = True
            elif tick - self.final_tick >= 400:
                self.failure = "final_stand_timeout"
        return frame

    def snapshot(self, frame):
        return {
            "phase": self.phase,
            "frame": frame,
            "walk_start": self.walk_start,
            "brake_frame": self.brake_frame,
            "brake_tick": self.brake_tick,
            "final_tick": self.final_tick,
            "walk_origin": (
                None if self.walk_origin is None else self.walk_origin.tolist()
            ),
            "done": self.done,
            "failure": self.failure,
        }
