"""Candidate motor-command guard using every sole point and measured dynamics.

All hypothetical dynamics are evaluated in scratch MjData. Only bounded existing
leg motor commands may change in the live state; no physical parameters change.
The acceleration barrier is a controller candidate, not a production guarantee.
"""
import time
import numpy as np
import mujoco
from scipy.optimize import minimize


class AllSoleGuard:
    def __init__(self, model, omega=20., guard_m=.006, activation_m=.08,
                 max_delta_Nm=8., max_iterations=30):
        self.model = model
        self.scratch = mujoco.MjData(model)
        self.state = np.empty(mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_INTEGRATION))
        self.aids = np.array([model.actuator(side + '_' + name + '_joint').id
                             for side in ['left', 'right']
                             for name in ['hip_pitch', 'hip_roll', 'hip_yaw', 'knee', 'ankle_pitch', 'ankle_roll']])
        bodies = [model.body(side + '_ankle_roll_link').id for side in ['left', 'right']]
        self.geoms = [g for g in range(model.ngeom)
                      if int(model.geom_bodyid[g]) in bodies
                      and model.geom_type[g] == mujoco.mjtGeom.mjGEOM_SPHERE
                      and (model.geom_contype[g] or model.geom_conaffinity[g])]
        assert len(self.geoms) == 8
        self.omega, self.guard, self.activation = omega, guard_m, activation_m
        self.max_delta, self.max_iterations = max_delta_Nm, max_iterations
        self.base_limits = np.array([.5, .5, .5, 2., 2., 2.])
        self.previous = np.zeros(len(self.aids))

    def apply(self, live):
        started = time.monotonic()
        m, d = self.model, self.scratch
        baseline = live.ctrl.copy()
        mujoco.mj_getState(m, live, self.state, mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_setState(m, d, self.state, mujoco.mjtState.mjSTATE_INTEGRATION)
        mujoco.mj_forward(m, d)
        J, bias, height, speed = [], [], [], []
        for g in self.geoms:
            jp = np.zeros((3, m.nv)); jr = np.zeros_like(jp)
            jd = np.zeros_like(jp); jdr = np.zeros_like(jp)
            body, point = int(m.geom_bodyid[g]), d.geom_xpos[g].copy()
            mujoco.mj_jac(m, d, jp, jr, point, body)
            mujoco.mj_jacDot(m, d, jd, jdr, point, body)
            J.append(jp[2].copy()); bias.append(float(jd[2] @ d.qvel))
            height.append(float(point[2] - m.geom_size[g, 0]))
            speed.append(float(jp[2] @ d.qvel))
        J, bias, height, speed = map(np.asarray, [J, bias, height, speed])
        offset = bias + 2 * self.omega * speed + self.omega**2 * (height + self.guard)
        original = J @ d.qacc + offset
        base_acceleration = d.qacc[:6].copy()
        active = height < self.activation
        count = 1
        delta = np.zeros(len(self.aids))
        optimized = bool(np.any(active) and min(original[active]) < -1e-4)
        accepted = False
        message = 'nominal_barrier_satisfied'
        actual = original.copy()
        base_change = np.zeros(6)
        if optimized:
            low = np.maximum(-self.max_delta, m.actuator_ctrlrange[self.aids, 0] - baseline[self.aids])
            high = np.minimum(self.max_delta, m.actuator_ctrlrange[self.aids, 1] - baseline[self.aids])
            def constraints(value):
                nonlocal count
                d.ctrl[:] = baseline
                d.ctrl[self.aids] += value
                # Reuse exactly the saved solver warmstart, so evaluation order
                # cannot become hidden controller memory.
                d.qacc_warmstart[:] = live.qacc_warmstart
                mujoco.mj_forward(m, d)
                count += 1
                change = d.qacc[:6] - base_acceleration
                return np.r_[(J @ d.qacc + offset)[active],
                             self.base_limits - change, self.base_limits + change]
            result = minimize(lambda x: .5 * float(x @ x), np.clip(self.previous, low, high),
                              jac=lambda x: x, method='SLSQP', bounds=list(zip(low, high)),
                              constraints=[{'type': 'ineq', 'fun': constraints}],
                              options={'maxiter': self.max_iterations, 'ftol': 1e-8, 'eps': 1e-4})
            values = constraints(result.x)
            # This is a numerical optimizer residual tolerance, not a relaxation
            # of the unchanged10mm penetration/forbidden-contact quality gates.
            accepted = bool(np.isfinite(result.x).all() and min(values) >= -1e-4)
            message = str(result.message)
            if accepted:
                delta = result.x.copy()
                actual = J @ d.qacc + offset
                base_change = d.qacc[:6] - base_acceleration
        live.ctrl[self.aids] = baseline[self.aids] + delta
        self.previous = delta.copy()
        return {'optimized': optimized, 'candidate_accepted': accepted,
                'geom_names': [m.geom(g).name for g in self.geoms],
                'height_m': height.tolist(), 'vertical_velocity_mps': speed.tolist(),
                'nominal_barrier': original.tolist(), 'issued_barrier': actual.tolist(),
                'active_mask': active.tolist(), 'motor_delta_Nm': delta.tolist(),
                'base_acceleration_change': base_change.tolist(),
                'scratch_forward_calls': count, 'optimizer_message': message,
                'wall_seconds': time.monotonic() - started}
