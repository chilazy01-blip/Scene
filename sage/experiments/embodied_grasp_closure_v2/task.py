"""Actual native action consumer. This module never integrates or resets physics.

The caller supplies an already-forwarded current MjData. The adapter validates
the entire named action before updating its state. Rejections do not write ctrl.
Only native observations can populate its trial-lift evidence window.
"""
from copy import deepcopy
import numpy as np

from .control import ClosureController
from sage.experiments.embodied_grasp_closure_v1.control import observation
from sage.experiments.embodied_grasp_validation_v1.native import NAMES
from sage.experiments.embodied_grasp_validation_v1.quality import (
    contact_quality, relative_pose, pose_drift, test_lift_gate)


class TrialGate:
    phases = ('close', 'test_lift', 'test_hold', 'lift', 'transport', 'place')

    def __init__(self, limits, contract):
        self.limits, self.c = limits, contract
        self.phase = 'close'
        self.samples = []
        self.passed = False
        self.failed = False

    def admit(self, phase, decision):
        if phase not in self.phases:
            raise ValueError('unsupported_phase')
        old, new = self.phases.index(self.phase), self.phases.index(phase)
        if new not in (old, old + 1):
            raise ValueError('phase_order')
        if self.failed or decision['state'] == 'failed':
            self.failed = True
            return ['controller_failed']
        reasons = []
        if phase != 'close' and not decision['ready']:
            reasons.append('load_and_reference_not_ready')
        if new >= self.phases.index('lift') and not self.passed:
            reasons.append('transport_requires_actual_trial_window')
        if reasons:
            self.failed = True
        else:
            self.phase = phase
        return reasons

    def record(self, sample):
        if self.phase != 'test_hold' or self.failed:
            raise ValueError('trial_sample_out_of_phase')
        # Only the complete contiguous tail qualifies; input time cannot be guessed.
        if not np.isfinite(sample['time']):
            raise ValueError('nonfinite_trial_time')
        if self.samples and abs(sample['time'] - self.samples[-1]['time'] - self.c.dt) > 1e-9:
            raise ValueError('trial_timestamp_gap')
        self.samples.append(deepcopy(sample))
        self.samples = self.samples[-round(self.limits['window_seconds'] / self.c.dt):]

    def finish(self):
        reasons = test_lift_gate(self.samples, self.limits, self.c.dt)
        if self.phase != 'test_hold':
            reasons.append('trial_not_held')
        if any(min(s['contact_quality'][side]['force_N'] for side in ('left', 'right'))
               < self.c.contact_force_min for s in self.samples):
            reasons.append('trial_nominal_load_insufficient')
        if self.failed:
            reasons.append('task_failed')
        self.failed |= bool(reasons)
        self.passed = not self.failed
        return reasons


class NativeTaskConsumer:
    def __init__(self, native, task, contract, limits):
        self.native, self.task = native, task
        self.controller = ClosureController(contract)
        self.gate = TrialGate(limits, contract)
        self.reference = None
        self.com_height = None
        self.passive_dofs = [int(native.m.jnt_dofadr[native.m.joint(n).id]) for n in
                             ('rubber_left_x', 'rubber_left_y', 'rubber_right_x', 'rubber_right_y')]
        m = native.m
        if not (m.actuator_gainprm[5, 0] == contract.kp and m.actuator_biasprm[5, 1] == -contract.kp
                and m.actuator_biasprm[5, 2] == -contract.kd and m.actuator_gear[5, 0] == 1
                and m.opt.timestep == contract.dt
                and np.array_equal(m.actuator_ctrlrange[5], [contract.ctrl_min, contract.ctrl_max])):
            raise ValueError('native_contract_mismatch')

    def consume(self, data, values, phase='close', names=NAMES, units='native_m_rad'):
        native, c = self.native, self.controller.c
        if tuple(names) != NAMES or units != 'native_m_rad':
            raise ValueError('native_names_or_units')
        a = np.asarray(values, float).copy()
        if a.shape != (8,) or not np.isfinite(a).all():
            raise ValueError('action_shape_or_nonfinite')
        limited = native.m.actuator_ctrllimited.astype(bool)
        if (np.any(a[limited] < native.m.actuator_ctrlrange[limited, 0])
                or np.any(a[limited] > native.m.actuator_ctrlrange[limited, 1])):
            raise ValueError('native_action_range')
        quality = contact_quality(native.contacts(data), data.xipos[native.target],
                                  data.xmat[native.target].reshape(3, 3),
                                  self.task['mass_kg'], self.task['friction'][0])
        ob = observation(data.time, data.actuator_length[5], data.actuator_velocity[5],
                         data.actuator_force[5], quality, max(abs(data.qvel[self.passive_dofs])))
        controller, gate = deepcopy(self.controller), deepcopy(self.gate)
        decision = controller.update(float(a[5]), ob, float(data.ctrl[5]))
        reasons = gate.admit(phase, decision)
        current = relative_pose(data.xpos[native.hand], data.xmat[native.hand].reshape(3, 3),
                                data.xipos[native.target], data.xmat[native.target].reshape(3, 3))
        reference, com_height = self.reference, self.com_height
        if phase == 'test_lift' and reference is None and not reasons:
            reference, com_height = current, float(data.xipos[native.target, 2])
        if phase == 'test_hold' and not reasons:
            slip, rotation = pose_drift(reference, current)
            support_force = 0.
            import mujoco
            for i, contact in enumerate(data.contact):
                if set(map(int, native.m.geom_bodyid[[contact.geom1, contact.geom2]])) == {native.target, native.support}:
                    f = np.zeros(6); mujoco.mj_contactForce(native.m, data, i, f)
                    support_force += max(0., float(f[0]))
            bottom = min(np.asarray(self.task['local_vertices']) @ data.xmat[native.target].reshape(3, 3)[2]) + data.xpos[native.target, 2]
            gate.record(dict(time=float(data.time), contact_quality=quality,
                             relative_slip_m=slip, relative_rotation_rad=rotation,
                             object_lift_m=float(data.xipos[native.target, 2] - com_height),
                             support_clearance_m=float(bottom - self.task['support_top_z']),
                             support_force_N=support_force))
        if not reasons:
            a[5] = decision['command']
            native.command(data, a, names, units)
        self.controller, self.gate = controller, gate
        self.reference, self.com_height = reference, com_height
        return dict(decision=decision, failures=reasons, applied=not reasons,
                    observation=ob, command=None if reasons else a.tolist(),
                    force_semantics=dict(slider_generalized_N=ob['native_force'],
                                         side_normal_N=[ob['left_force'], ob['right_force']],
                                         load_threshold_is_prior=True,
                                         legacy_5N_margin_is_diagnostic_only=True))

    def finish_trial(self):
        return self.gate.finish()
