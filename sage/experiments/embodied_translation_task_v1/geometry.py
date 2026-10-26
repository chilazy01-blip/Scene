"""Fixed two-footprint contact region; no outcome-dependent placement."""
import numpy as np


def translation_region(start_xy, goal_xy, extents_xy, pitch, extra):
    def lattice(value):
        nearest=np.rint(value)
        return np.where(abs(value-nearest)<1e-10,nearest,value)
    low = np.floor(lattice((np.minimum(start_xy, goal_xy)-np.asarray(extents_xy)/2-extra)/pitch))*pitch
    high = np.ceil(lattice((np.maximum(start_xy, goal_xy)+np.asarray(extents_xy)/2+extra)/pitch))*pitch
    return np.array([low, high]), np.rint((high-low)/pitch).astype(int)
