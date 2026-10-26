"""Compile validated timing proposals into the unchanged expert's reference paths."""
import numpy as np
from sage.experiments.embodied_native_sonic_body_grasp_v1.task_stand import Task as Previous
from sage.experiments.embodied_native_sonic_grasp_feedback_v1.continuous_lift import make_path
from .proposal import validate


class Task(Previous):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        proposal = self.case.get("codex_reference_proposal")
        self.reference_proposal = None if proposal is None else validate(proposal)

    def move(self, tick, data, goal, rotation, duration=65):
        if self.reference_proposal is None or self.stage not in ("place", "retract"):
            return super().move(tick, data, goal, rotation, duration)
        position, orientation = self.desired(tick)
        if self.stage == "place":
            goal = np.asarray(self.case["target_object_xyz_m"]) - self.grasp_R @ np.asarray(self.last_object_local)
            duration = self.reference_proposal["place_duration_ticks"]
        else:
            duration = self.reference_proposal["retract_duration_ticks"]
        self.path = make_path(tick, position, orientation, goal, self.grasp_R, duration)
        self.joint_path = None
        self.events.append(dict(kind="codex_proposal_compiled_cartesian_path", tick=tick, stage=self.stage,
                                origin=position.tolist(), goal=np.asarray(goal).tolist(), duration=duration,
                                rotation=self.grasp_R.tolist(), origin_source="previous_desired_reference",
                                original_endpoints_physics_and_acceptance_preserved=True))
        self.synchronize(tick, data, force=True)
