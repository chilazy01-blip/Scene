"""D candidate: retain a measured encoder reference after stable capture.

The retained position actuators, their force limits and plant stay unchanged.
This is a physical joint servo candidate, not an object constraint or weld.
"""
import numpy as np
from .contact_finger_governor_r2 import ContactFingerGovernor


class MeasuredFingerHold(ContactFingerGovernor):
    def __init__(self, model, **kwargs):
        super().__init__(model, **kwargs)
        self.holding = False
        self.reference = {}

    def hold(self, m, d):
        self.holding = True
        for a, qa, digit in zip(self.aids, self.qa, self.digits):
            if digit in self.latched:
                self.reference[int(a)] = float(np.clip(d.ctrl[a], d.qpos[qa] - self.cap, d.qpos[qa] + self.cap))

    def release(self):
        self.holding = False
        self.reference = {}

    def apply(self, m, d):
        rows = super().apply(m, d)
        if self.holding:
            for i, (a, qa, digit) in enumerate(zip(self.aids, self.qa, self.digits)):
                if digit not in self.latched:
                    continue
                key = int(a)
                if key not in self.reference:
                    self.reference[key] = float(d.ctrl[a])
                q = float(d.qpos[qa])
                target = np.clip(self.reference[key], q - self.cap, q + self.cap)
                d.ctrl[a] = np.clip(target, *m.actuator_ctrlrange[a])
                rows[i, 1] = 2
                rows[i, 5] = d.ctrl[a]
        return rows
