"""Persistent-data arm IK, reference-only, never writes the physical simulator."""

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from sage.experiments.embodied_transport_contact_v1.fast_kinematics import ARM_NAMES


class IK:
    def __init__(self, mujoco, model):
        self.mujoco, self.model = mujoco, model
        self.data = mujoco.MjData(model)
        self.qids = np.array([model.joint(n).qposadr[0] for n in ARM_NAMES], dtype=int)
        self.lower, self.upper = np.array([model.joint(n).range for n in ARM_NAMES]).T
        self.wrist = model.body("right_wrist_yaw_link").id

    def solve(self, qpos, position, rotation, max_evaluations=80):
        d, m = self.data, self.model
        d.qpos[:] = qpos
        initial = np.clip(d.qpos[self.qids], self.lower + 1e-5, self.upper - 1e-5)

        def residual(angles):
            d.qpos[self.qids] = angles
            self.mujoco.mj_kinematics(m, d)
            actual = d.xmat[self.wrist].reshape(3, 3)
            return np.r_[
                10 * (d.xpos[self.wrist] - position),
                Rotation.from_matrix(rotation.T @ actual).as_rotvec(),
                0.005 * (angles - initial),
            ]

        fit = least_squares(
            residual,
            initial,
            bounds=(self.lower + 1e-5, self.upper - 1e-5),
            max_nfev=max_evaluations,
            ftol=1e-9,
            xtol=1e-9,
            gtol=1e-9,
        )
        residual(fit.x)
        return {
            "angles_rad": fit.x.tolist(),
            "position_error_m": float(np.linalg.norm(d.xpos[self.wrist] - position)),
            "orientation_error_rad": float(
                np.linalg.norm(
                    Rotation.from_matrix(
                        rotation.T @ d.xmat[self.wrist].reshape(3, 3)
                    ).as_rotvec()
                )
            ),
            "evaluations": fit.nfev,
        }
