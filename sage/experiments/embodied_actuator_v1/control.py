"""Native MuJoCo transmissions, virtual work, and all-or-nothing admission.

Diagnostic calculations do not confer a hardware effort limit. There is no
external-force or integration fallback when a source specification is missing.
"""
import numpy as np

CHANNELS = ('left_wheel_vel', 'right_wheel_vel', 'lift', 'arm',
            'wrist_yaw', 'wrist_pitch', 'wrist_roll', 'gripper', 'head_pan', 'head_tilt')


class AdmissionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise AdmissionError(message)


class StretchTransmission:
    """dq = S dz, where arm z is total extension and gripper z is slider m.

    Wheel z is wheel angle (rad), while native velocity ctrl uses geared
    actuator velocity (3 rad of transmission per rad of wheel rotation).
    Equality-coupled fingers contribute through virtual work, not force sums.
    """
    def __init__(self, model):
        import mujoco
        require(tuple(model.actuator(i).name for i in range(model.nu)) == CHANNELS,
                'native channel names/order mismatch')
        require(model.neq == 5, 'unexpected coupling count')
        self.model = model
        self.S = np.zeros((model.nv, model.nu))
        self.joints = {}
        arms = tuple('joint_arm_l' + str(i) for i in range(4))
        fingers = ('joint_gripper_finger_left_open', 'joint_gripper_finger_right_open')
        for a, name in enumerate(CHANNELS):
            pairs = ([(j, .25) for j in arms] if name == 'arm' else
                     [(model.joint(int(model.actuator_trnid[a, 0])).name, 1.)])
            if name == 'arm':
                require(model.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_TENDON,
                        'arm must use a tendon')
            else:
                require(model.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT,
                        'direct joint transmission expected')
            if name == 'gripper':
                pairs += [(j, 10.) for j in fingers]
            self.joints[name] = tuple(pairs)
            for j, factor in pairs:
                joint = model.joint(j)
                require(joint.type[0] in (mujoco.mjtJoint.mjJNT_SLIDE, mujoco.mjtJoint.mjJNT_HINGE),
                        'scalar joint required')
                self.S[int(joint.dofadr[0]), a] = factor
        # Validate actual polynomial equality semantics, not only joint names.
        for e in range(model.neq):
            require(model.eq_type[e] == mujoco.mjtEq.mjEQ_JOINT and model.eq_active0[e],
                    'active joint equality required')
            j1, j2 = int(model.eq_obj1id[e]), int(model.eq_obj2id[e])
            c = model.eq_data[e, :5]
            require(c[0] == 0 and np.all(c[2:] == 0), 'nonlinear/offset coupling unsupported')
            require(np.allclose(self.S[model.jnt_dofadr[j1]], c[1] * self.S[model.jnt_dofadr[j2]],
                                atol=1e-14, rtol=0), 'coupling derivative mismatch')
        self.S.setflags(write=False)

    def moments(self, data):
        moment = np.asarray(data.actuator_moment)
        if moment.shape == (self.model.nu, self.model.nv):
            return moment.copy()
        require(moment.ndim == 1 and hasattr(data, 'moment_rownnz'), 'unsupported moment storage')
        dense = np.zeros((self.model.nu, self.model.nv))
        for row in range(self.model.nu):
            start = int(data.moment_rowadr[row])
            stop = start + int(data.moment_rownnz[row])
            columns = data.moment_colind[start:stop]
            require(len(set(columns.tolist())) == len(columns), 'duplicate moment column')
            dense[row, columns] = moment[start:stop]
        return dense

    def matrix(self, data):
        moment = self.moments(data)
        matrix = self.S.T @ moment.T
        require(np.all(np.isfinite(matrix)) and np.linalg.matrix_rank(matrix) == self.model.nu,
                'singular/nonfinite actuator transmission')
        # Free-base and object coordinates must never receive direct actuation.
        untouched = np.all(self.S == 0, axis=1)
        require(np.all(moment[:, untouched] == 0), 'unexpected base/object actuation')
        return matrix

    def gravity(self, stationary_data):
        """Requires an independently evaluated zero-velocity MjData."""
        require(not np.any(stationary_data.qvel), 'gravity data must have zero velocity')
        require(not np.any(self.model.body_gravcomp), 'external body support forbidden')
        require(not np.any(stationary_data.qfrc_applied) and not np.any(stationary_data.xfrc_applied),
                'external forces forbidden')
        generalized = self.S.T @ stationary_data.qfrc_bias
        return np.linalg.solve(self.matrix(stationary_data), generalized)

    def perturb(self, qpos, channel, delta):
        result = np.array(qpos, dtype=float, copy=True)
        for name, factor in self.joints[channel]:
            result[self.model.joint(name).qposadr[0]] += factor * delta
        return result


class AffineServo:
    def __init__(self, model):
        import mujoco
        require(tuple(model.actuator(i).name for i in range(model.nu)) == CHANNELS,
                'native channel names/order mismatch')
        require(np.all(model.actuator_gaintype == mujoco.mjtGain.mjGAIN_FIXED), 'fixed gains required')
        require(np.all(model.actuator_biastype == mujoco.mjtBias.mjBIAS_AFFINE), 'affine servos required')
        require(np.all(model.actuator_dyntype == mujoco.mjtDyn.mjDYN_NONE), 'activation dynamics unsupported')
        self.model = model
        self.gain = model.actuator_gainprm[:, 0].copy()
        self.bias = model.actuator_biasprm[:, :3].copy()
        require(np.all(np.isfinite(self.gain)) and np.all(self.gain > 0), 'positive finite gains required')

    def diagnostic(self, data, native_reference, gravity_force):
        """Pure calculation: neither installs bounds nor writes ctrl/model state."""
        ref = np.asarray(native_reference, dtype=float)
        ff = np.asarray(gravity_force, dtype=float)
        require(ref.shape == ff.shape == (len(CHANNELS),), 'command shape mismatch')
        require(np.all(np.isfinite(ref)) and np.all(np.isfinite(ff)), 'nonfinite command')
        ctrl = ref + ff / self.gain
        force = (self.gain * ctrl + self.bias[:, 0] +
                 self.bias[:, 1] * data.actuator_length + self.bias[:, 2] * data.actuator_velocity)
        require(np.all(np.isfinite(ctrl)) and np.all(np.isfinite(force)), 'nonfinite servo result')
        return ctrl, force

    def validated_limits(self, registry):
        require(set(registry) == set(CHANNELS), 'effort registry incomplete')
        bounds = []
        for a, name in enumerate(CHANNELS):
            row = registry[name]
            require(row.get('qualified') is True and row.get('source_sha256') and
                    row.get('transmission_verified') is True,
                    'missing credible effort/transmission specification: ' + name)
            require(row.get('coordinate') == 'native_actuator_force', 'wrong effort coordinate: ' + name)
            expected_unit = 'N' if name in ('lift', 'arm', 'gripper') else 'N*m'
            require(row.get('unit') == expected_unit, 'wrong effort unit: ' + name)
            bound = np.asarray(row.get('range'), dtype=float)
            require(bound.shape == (2,) and np.all(np.isfinite(bound)) and bound[0] < 0 < bound[1],
                    'finite signed effort bounds required: ' + name)
            if self.model.actuator_forcelimited[a]:
                bound = np.array([max(bound[0], self.model.actuator_forcerange[a, 0]),
                                  min(bound[1], self.model.actuator_forcerange[a, 1])])
            bounds.append(bound)
        return np.array(bounds)

    def prepare(self, data, native_reference, gravity_force, registry):
        """Reject an incomplete or infeasible command before any state mutation."""
        require(not np.any(self.model.body_gravcomp) and not np.any(data.qfrc_applied)
                and not np.any(data.xfrc_applied), 'external support forbidden')
        limits = self.validated_limits(registry)
        ctrl, force = self.diagnostic(data, native_reference, gravity_force)
        limited = self.model.actuator_ctrllimited.astype(bool)
        require(np.all(ctrl[limited] >= self.model.actuator_ctrlrange[limited, 0]) and
                np.all(ctrl[limited] <= self.model.actuator_ctrlrange[limited, 1]), 'ctrl range infeasible')
        require(np.all(force >= limits[:, 0]) and np.all(force <= limits[:, 1]), 'effort range infeasible')
        return ctrl, limits

    def apply(self, data, native_reference, gravity_force, registry):
        ctrl, limits = self.prepare(data, native_reference, gravity_force, registry)
        # All validation above; these are the only mutations. No gain or bias edit.
        self.model.actuator_forcerange[:] = limits
        self.model.actuator_forcelimited[:] = True
        data.ctrl[:] = ctrl
        return ctrl.copy()
