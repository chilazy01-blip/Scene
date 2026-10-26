"""Bounded seven-joint reference IK; never an actuator/body-command override."""

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

ARM_NAMES = tuple(
    "right_" + n + "_joint"
    for n in (
        "shoulder_pitch",
        "shoulder_roll",
        "shoulder_yaw",
        "elbow",
        "wrist_roll",
        "wrist_pitch",
        "wrist_yaw",
    )
)


def solve(mujoco, model, qpos, position, rotation, *, max_evaluations=150):
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    joints = [model.joint(n) for n in ARM_NAMES]
    qids = np.array([j.qposadr[0] for j in joints], dtype=int)
    lower, upper = np.array([j.range for j in joints]).T
    initial = data.qpos[qids].copy()
    wrist = model.body("right_wrist_yaw_link").id

    def residual(angles):
        data.qpos[qids] = angles
        mujoco.mj_forward(model, data)
        actual = data.xmat[wrist].reshape(3, 3)
        return np.r_[
            10 * (data.xpos[wrist] - position),
            Rotation.from_matrix(rotation.T @ actual).as_rotvec(),
            0.005 * (angles - initial),
        ]

    result = least_squares(
        residual,
        initial,
        bounds=(lower + 1e-5, upper - 1e-5),
        max_nfev=max_evaluations,
        ftol=1e-10,
        xtol=1e-10,
        gtol=1e-10,
    )
    residual(result.x)
    return {
        "joint_names": list(ARM_NAMES),
        "angles_rad": result.x.tolist(),
        "position_error_m": float(np.linalg.norm(data.xpos[wrist] - position)),
        "orientation_error_rad": float(
            np.linalg.norm(
                Rotation.from_matrix(
                    rotation.T @ data.xmat[wrist].reshape(3, 3)
                ).as_rotvec()
            )
        ),
        "evaluations": result.nfev,
        "joint_limit_margin_rad": float(
            np.min(np.minimum(result.x - lower, upper - result.x))
        ),
    }
