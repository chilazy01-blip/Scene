"""Backout with initial finger clearance directed away from shelf posts."""
from .release_backout_r2 import Recover as Original


class Recover(Original):
    def __init__(self, m, c, robot, d, command, end_goal):
        super().__init__(m, c, robot, d, command, end_goal)
        for side, outward in self.withdraw.direction.items():
            # Keep a lateral separation component while bringing free palms
            # backward; a purely outward withdrawal approaches shelf posts.
            self.withdraw.direction[side] = .5 * outward + self.backward
