"""Recover upright while flexing unloaded elbows, retaining the grasp-side clearance."""
import numpy as np
from .release_corridor import Recover as Corridor


class Recover(Corridor):
    def __init__(self, m, c, robot, d, command, configuration):
        target = command.copy()
        names = c['joint_names']
        for name, offset in configuration['joint_offsets'].items():
            target[names.index(name)] += offset
        for name, value in configuration['joint_targets'].items():
            target[names.index(name)] = value
        upper = np.array(robot.get_joint_group_indices('upper_body'))
        plan = dict(neutral_goal=dict(
            target_upper_body_pose=target[upper],
            base_height_command=configuration['base_height_command']),
            joint_excursion={})
        super().__init__(m, c, robot, d, command, plan)
