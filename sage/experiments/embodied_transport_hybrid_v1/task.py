"""Standing pickup/place qualification, then the same continuous transport FSM."""

import numpy as np
from sage.experiments.embodied_transport_v1.task_r6 import Task as ParentTask


class Task(ParentTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.case["task_mode"] == "standing_pick_place":
            self.q[:] = self.q[0]
            self.v[:] = 0
            self.stage = "source_stop"
            self.stop_frame = 0
            self.walk_goal = np.array(self.case["start_xy_m"])

    def transition(self, stage, frame, metrics):
        if stage == "carry" and self.case["task_mode"] == "standing_pick_place":
            stage = "place"
        super().transition(stage, frame, metrics)

    def begin_carry(self, frame, data):
        if self.case["task_mode"] != "standing_pick_place":
            return super().begin_carry(frame, data)

    def snapshot(self, frame):
        snapshot = super().snapshot(frame)
        snapshot["task_mode"] = self.case["task_mode"]
        return snapshot
