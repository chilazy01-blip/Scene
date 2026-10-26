"""Stage completion and release/retreat around the immutable native consumer."""
from copy import deepcopy
import numpy as np
from sage.experiments.embodied_grasp_closure_v2.task import NativeTaskConsumer
from sage.experiments.embodied_grasp_validation_v1.native import NAMES
from sage.experiments.embodied_grasp_closure_v1.execution import target_at, CLOSED_PHASES


class CompleteTaskConsumer:
    def __init__(self, native, task, contract, limits, sequence):
        self.native = native
        self.closed = NativeTaskConsumer(native, task, contract, limits)
        self.sequence = {p['id']: deepcopy(p) for p in sequence if p['id'] in CLOSED_PHASES + ('release', 'retreat', 'settle')}
        self.order = tuple(self.sequence)
        assert self.order == CLOSED_PHASES + ('release', 'retreat', 'settle')
        self.phase = None
        self.count = 0
        self.finished = set()
        self.failed = False
        self.last_time = self.last_grip = None
        self.release_handoff = None

    def validate_action(self, values, names=NAMES, units='native_m_rad'):
        if tuple(names) != NAMES or units != 'native_m_rad':
            raise ValueError('native_names_or_units')
        a = np.asarray(values, dtype=float).copy()
        if a.shape != (8,) or not np.isfinite(a).all():
            raise ValueError('action_shape_or_nonfinite')
        m = self.native.m
        limited = m.actuator_ctrllimited.astype(bool)
        if np.any(a[limited] < m.actuator_ctrlrange[limited, 0]) or np.any(a[limited] > m.actuator_ctrlrange[limited, 1]):
            raise ValueError('native_action_range')
        return a

    def begin_release(self, data):
        if self.failed or self.phase != 'place' or 'place' not in self.finished or not self.closed.gate.passed:
            raise ValueError('release_requires_completed_place_and_trial')
        if self.release_handoff is not None:
            raise ValueError('release_already_initialized')
        c = self.closed.controller.c
        if not self.closed.controller.ready:
            raise ValueError('release_requires_last_place_readiness')
        if abs(float(data.ctrl[5]) - self.last_grip) > c.command_tolerance:
            raise ValueError('release_previous_command_not_applied')
        if abs(float(data.time) - self.last_time - c.dt) > 1e-9:
            raise ValueError('release_timestamp_gap')
        phase = self.sequence['release']
        phase['initial'][5] = float(data.ctrl[5])
        handoff = dict(time=float(data.time), last_applied_grip=float(data.ctrl[5]),
                       initial_grip=phase['initial'][5], position=float(data.actuator_length[5]),
                       velocity=float(data.actuator_velocity[5]), native_force=float(data.actuator_force[5]))
        handoff['same_state_force_jump_N'] = c.kp * (handoff['initial_grip'] - handoff['last_applied_grip'])
        self.release_handoff = handoff
        return deepcopy(phase)

    def consume(self, data, values, phase, names=NAMES, units='native_m_rad'):
        a = self.validate_action(values, names, units)
        if phase not in self.order:
            raise ValueError('unsupported_task_phase')
        index = self.order.index(phase)
        if self.phase != phase:
            if (index == 0 and self.phase is not None) or (index and self.order[index-1] not in self.finished):
                raise ValueError('previous_phase_not_complete')
            count = 0
        else:
            count = self.count
        if phase in self.finished or count >= self.sequence[phase]['steps']:
            raise ValueError('phase_already_complete')
        if self.failed:
            return dict(applied=False, failures=['task_terminal_failure'], command=None)
        c = self.closed.controller.c
        if phase in CLOSED_PHASES:
            output = self.closed.consume(data, a, phase, names, units)
        else:
            if self.release_handoff is None:
                raise ValueError('release_handoff_missing')
            if abs(float(data.time) - self.last_time - c.dt) > 1e-9:
                raise ValueError('release_or_retreat_timestamp_gap')
            if abs(float(data.ctrl[5]) - self.last_grip) > c.command_tolerance:
                raise ValueError('release_or_retreat_previous_command_not_applied')
            expected = target_at(self.sequence[phase], count + 1, c.dt)
            if np.max(abs(a[2:] - expected[2:])) > 1e-12:
                raise ValueError('release_or_retreat_reference_mismatch')
            self.native.command(data, a, names, units)
            output = dict(applied=True, failures=[], command=a.tolist(),
                          decision=dict(state=phase, command=float(a[5]), reason=None),
                          observation=dict(time=float(data.time), position=float(data.actuator_length[5]),
                                           velocity=float(data.actuator_velocity[5]), native_force=float(data.actuator_force[5])))
        self.failed |= not output['applied']
        if output['applied']:
            self.phase, self.count = phase, count + 1
            self.last_time, self.last_grip = float(data.time), float(data.ctrl[5])
        return output

    def finish_phase(self, phase):
        if self.failed or self.phase != phase or self.count != self.sequence[phase]['steps']:
            raise ValueError('phase_not_complete')
        if phase in self.finished:
            raise ValueError('phase_finish_repeated')
        reasons = []
        if phase == 'close' and not self.closed.controller.ready:
            reasons.append('closure_not_ready')
        if phase == 'test_hold':
            reasons += self.closed.finish_trial()
        self.failed |= bool(reasons)
        if not reasons:
            self.finished.add(phase)
        return reasons
