"""Causal bounded policy velocity requests; no plant or state changes."""
import numpy as np


class VelocityTransition:
    def __init__(self, caps, accelerations, period=.02):
        self.caps = np.asarray(caps, float)
        self.accelerations = np.asarray(accelerations, float)
        self.period = float(period)
        assert self.caps.shape == self.accelerations.shape == (3,)
        assert np.all(self.caps > 0) and np.all(self.accelerations > 0) and self.period > 0
        self.issued = np.zeros(3)

    def command(self, requested):
        capped = np.clip(np.asarray(requested, float), -self.caps, self.caps)
        change = self.accelerations * self.period
        self.issued += np.clip(capped - self.issued, -change, change)
        return self.issued.copy()
