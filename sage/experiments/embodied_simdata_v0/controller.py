"""Portable v0 controller, derived from the pinned helper below.
The v0 revision adds a 0.01 continuity regularizer to reference IK only.
Source: embodied_scene_v1/runner.py
Source SHA256: 729307013545886f01c0de8abe00d74f831f9f4b18530b98be8774923115f873
"""
import numpy as np
import mujoco
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares


class PandaController:
    def __init__(self, m, d):
        self.m, self.d = m, d
        self.joints = [m.joint(f'joint{i}').id for i in range(1, 8)]
        self.qi = m.jnt_qposadr[self.joints]; self.vi = m.jnt_dofadr[self.joints]
        self.ai = np.array([m.actuator(f'torq_j{i}').id for i in range(1, 8)])
        self.fi = [m.actuator('gripper_finger_joint1').id, m.actuator('gripper_finger_joint2').id]
        self.site = m.site('grip_site').id
        self.ikdata = mujoco.MjData(m)
        self.qhome = np.array([0, -.6, 0, -2.2, 0, 1.7, .8])
        self.target_rot = np.diag([1., -1., -1.])
        self.kp = np.array([400, 400, 400, 400, 200, 100, 80.])
        self.kd = np.array([45, 45, 45, 45, 25, 15, 12.])
    def ik(self, xyz, seed):
        d, m = self.ikdata, self.m
        d.qpos[:] = self.d.qpos
        anchor = np.asarray(seed).copy()
        def residual(q):
            d.qpos[self.qi] = q
            mujoco.mj_kinematics(m, d)
            rot = d.site_xmat[self.site].reshape(3, 3)
            return np.r_[np.asarray(xyz)-d.site_xpos[self.site],
                         Rotation.from_matrix(self.target_rot @ rot.T).as_rotvec(), .01*(q-anchor)]
        lo = m.jnt_range[self.joints,0]+.005; hi = m.jnt_range[self.joints,1]-.005
        result = least_squares(residual, np.clip(seed,lo,hi), bounds=(lo,hi), max_nfev=250,
                               xtol=1e-10, ftol=1e-10, gtol=1e-10)
        return result.x.copy(), float(np.linalg.norm(result.fun[:6]))
    def action(self, q, grip):
        force = self.kp*(q-self.d.qpos[self.qi]) - self.kd*self.d.qvel[self.vi] + self.d.qfrc_bias[self.vi]
        self.d.ctrl[self.ai] = np.clip(force, self.m.actuator_ctrlrange[self.ai, 0], self.m.actuator_ctrlrange[self.ai, 1])
        self.d.ctrl[self.fi] = [grip, -grip]
