"""Slower carry-only reference braking; clear expired world-space task goals."""

import numpy as np
from sage.experiments.embodied_transport_contact_v2.task import Task as ParentTask
from sage.experiments.embodied_transport_v1.task import smooth
from sage.experiments.embodied_data_stability_v1 import (
    sonic_native_dynamic_shadow as native,
)


class Task(ParentTask):
    def begin_carry(self, frame, data):
        super().begin_carry(frame, data)
        if self.case["task_mode"] == "full_transport":
            self.world_path = None

    def brake(self, frame):
        if self.walk_start == 0:
            return super().brake(frame)
        duration = int(self.case["carry_brake_duration_ticks"])
        target = self.walk_start_pose.copy()
        target[:2] = self.q[frame + duration, :2]
        target[3:7] = self.q[frame, 3:7]
        original = self.q.copy()
        for i in range(frame, len(self.q)):
            weight = float(smooth((i - frame) / duration))
            self.q[i, :3] = (1 - weight) * original[i, :3] + weight * target[:3]
            self.q[i, 3:7] = native._quaternion_slerp(
                original[i, 3:7], target[3:7], weight
            )
            self.q[i, 7:] = (1 - weight) * original[i, 7:] + weight * target[7:]
        self.v = native._reference_velocities(self.q)
        self.v[frame + duration :] = 0
        self.stop_frame = frame + duration
        self.reference_events.append(
            {
                "kind": "brake",
                "frame": frame,
                "stop": self.stop_frame,
                "duration": duration,
                "target": target.tolist(),
            }
        )
