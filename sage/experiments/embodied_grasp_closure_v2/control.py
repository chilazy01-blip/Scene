"""Bumpless position-reference transfer, with the native damping left intact.

Force continuity means comparing commands at the SAME (q, v). Changes in actual
force across time include motion/contact response and require separate checks.
"""
from dataclasses import dataclass
from math import isfinite

from sage.experiments.embodied_grasp_closure_v1.control import ClosureContract as V1Contract


@dataclass(frozen=True)
class ClosureContract(V1Contract):
    presence_force_min: float = .1
    transition_seconds: float = .1
    command_tolerance: float = 1e-12

    def __post_init__(self):
        super().__post_init__()
        if not (0 < self.presence_force_min < self.contact_force_min
                and self.transition_seconds > 0 and 0 < self.command_tolerance <= 1e-9):
            raise ValueError('invalid_transition_contract')
        for t in (self.confirm_seconds, self.loss_seconds, self.timeout_seconds):
            if abs(t / self.dt - round(t / self.dt)) > 1e-9:
                raise ValueError('nonintegral_duration')

    @property
    def max_command_step(self):
        return self.nominal_preload / self.kp * self.dt / self.transition_seconds


class ClosureController:
    def __init__(self, contract):
        self.c = contract
        self.state = 'closing'
        self.reason = None
        self.anchor = self.last_time = self.last_command = None
        self.steps = self.ready_steps = self.missing_steps = self.underload_steps = 0
        self.ready = False

    def fail(self, reason):
        self.state = 'failed'
        self.reason = reason
        self.ready = False
        return dict(state='failed', reason=reason, command=None, ready=False,
                    anchor=self.anchor, ready_steps=self.ready_steps,
                    missing_steps=self.missing_steps, underload_steps=self.underload_steps)

    def update(self, nominal, observed, applied):
        if self.state == 'failed':
            return self.fail(self.reason)
        c, o = self.c, observed
        keys = ('time', 'position', 'velocity', 'native_force', 'left_force',
                'right_force', 'left_pad_fraction', 'right_pad_fraction',
                'com_offset', 'passive_speed')
        # Malformed observations/actions never advance time or internal state.
        if any(k not in o for k in keys):
            raise ValueError('observation_schema')
        values = [nominal, applied] + [o[k] for k in keys if k != 'com_offset']
        if not all(isinstance(v, (int, float)) and isfinite(v) for v in values):
            raise ValueError('nonfinite_observation_or_command')
        if o['com_offset'] is not None and not (isfinite(o['com_offset']) and o['com_offset'] >= 0):
            raise ValueError('invalid_COM_offset')
        if any(o[s + '_force'] < 0 or not 0 <= o[s + '_pad_fraction'] <= 1 for s in ('left', 'right')):
            raise ValueError('invalid_contact_observation')
        if not c.ctrl_min <= applied <= c.ctrl_max or not c.ctrl_min <= nominal <= c.ctrl_max:
            raise ValueError('native_reference_range')
        if self.last_time is not None and abs(o['time'] - self.last_time - c.dt) > 1e-9:
            raise ValueError('timestamp_gap')
        if self.last_command is not None and abs(applied - self.last_command) > c.command_tolerance:
            raise ValueError('previous_command_not_applied')

        self.last_time = o['time']
        self.steps += 1
        self.ready = False
        q, v = o['position'], o['velocity']
        if abs(o['passive_speed']) > c.max_passive_speed:
            return self.fail('passive_speed')
        if abs(o['native_force']) > c.effort_limit + 1e-9:
            return self.fail('measured_native_effort')
        present = min(o['left_force'], o['right_force']) >= c.presence_force_min
        pad_pose = (min(o['left_pad_fraction'], o['right_pad_fraction']) >= c.min_pad_fraction
                    and o['com_offset'] is not None and o['com_offset'] <= c.max_com_offset)
        loaded = present and min(o['left_force'], o['right_force']) >= c.contact_force_min
        switch = self.state == 'closing' and loaded and pad_pose
        if switch:
            self.state, self.anchor = 'confirming', q
        active = self.state in ('confirming', 'holding')
        if active:
            if self.anchor - q > c.max_extra_compression + 1e-12:
                return self.fail('extra_compression')
            self.missing_steps = 0 if present else self.missing_steps + 1
            if present and not pad_pose:
                return self.fail('contact_part_or_COM_invalid')
            if self.missing_steps >= round(c.loss_seconds / c.dt):
                return self.fail('contact_missing')
            self.underload_steps = 0 if loaded else self.underload_steps + 1
            if self.state == 'holding' and self.underload_steps >= round(c.loss_seconds / c.dt):
                return self.fail('holding_load_insufficient')

        low = max(c.ctrl_min, q - c.max_target_deflection,
                  q + (-c.effort_limit + c.kd * v) / c.kp)
        high = min(c.ctrl_max, q + c.max_target_deflection,
                   q + (c.effort_limit + c.kd * v) / c.kp)
        target = q - c.nominal_preload / c.kp if active else nominal
        if switch:
            # Do not clip this reference and still label it a continuous switch.
            if applied < low or applied > high:
                return self.fail('switch_reference_infeasible')
            command = applied
        else:
            if active:
                low, high = max(low, applied - c.max_command_step), min(high, applied + c.max_command_step)
            if low > high:
                return self.fail('no_feasible_continuous_command' if active else 'no_feasible_native_command')
            command = min(max(target, low), high)

        settled = active and abs(command - target) <= c.command_tolerance
        self.ready_steps = self.ready_steps + 1 if settled and loaded and pad_pose else 0
        if active and self.ready_steps >= round(c.confirm_seconds / c.dt):
            self.state, self.ready = 'holding', True
        if self.state != 'holding' and self.steps >= round(c.timeout_seconds / c.dt):
            return self.fail('closure_timeout')
        self.last_command = command
        return dict(state=self.state, reason=None, command=command, ready=self.ready,
                    target=target, transition_settled=settled, switched=switch,
                    contact_present=present, pad_pose_valid=pad_pose, nominal_load_ready=loaded,
                    predicted_native_force=c.kp * (command - q) - c.kd * v,
                    previous_reference_force_at_current_state=c.kp * (applied - q) - c.kd * v,
                    force_change_from_reference_only=c.kp * (command - applied),
                    anchor=self.anchor, ready_steps=self.ready_steps,
                    missing_steps=self.missing_steps, underload_steps=self.underload_steps)
