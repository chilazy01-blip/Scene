"""SE(2)-equivariant observer anchor, using the unchanged official band law."""

import numpy as np
from sage.experiments.embodied_data_stability_v1.sonic_supported_shadow import (
    load_official_band,
)
from sage.experiments.embodied_data_stability_v1.sonic_native_full_shadow import (
    _quat_multiply,
)


class AnchoredBand:
    def __init__(self, xy, yaw):
        self.band = load_official_band()
        self.xy = np.asarray(xy)
        self.yaw = yaw
        c, s = np.cos(yaw), np.sin(yaw)
        self.rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        self.inverse_heading = np.array([np.cos(yaw / 2), 0, 0, -np.sin(yaw / 2)])

    def __getattr__(self, name):
        return getattr(self.band, name)

    @property
    def point(self):
        return np.array([*self.xy, 1.0])

    def Advance(self, pose):
        local = pose.copy()
        local[:3] = self.rotation.T @ (pose[:3] - np.array([*self.xy, 0.0]))
        local[3:7] = _quat_multiply(self.inverse_heading, pose[3:7])
        local[7:10] = self.rotation.T @ pose[7:10]
        local[10:13] = self.rotation.T @ pose[10:13]
        wrench = self.band.Advance(local)
        return np.r_[self.rotation @ wrench[:3], self.rotation @ wrench[3:]]
