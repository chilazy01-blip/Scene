"""Contact-aware native position commands with bounded preload and explicit failure.

The MuJoCo actuator remains kp*(u-q)-kd*v. In holding, u=q-preload/kp
retains native damping while requesting constant closing preload. A pre-step
force filter limits the requested native effort; measured effort is checked
separately because this filter is not a guarantee about post-step dynamics.
"""
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class ClosureContract:
    kp: float
    kd: float
    dt: float
    ctrl_min: float
    ctrl_max: float
    contact_force_min: float
    nominal_preload: float
    effort_limit: float
    confirm_seconds: float = .05
    loss_seconds: float = .02
    timeout_seconds: float = 2.
    max_extra_compression: float = .002
    max_target_deflection: float = .008
    min_pad_fraction: float = .8
    max_com_offset: float = .03
    max_passive_speed: float = 20.

    def __post_init__(self):
        if not all(isfinite(v) for v in vars(self).values()):
            raise ValueError('nonfinite_contract')
        if not (self.kp>0 and self.kd>=0 and self.dt>0 and self.ctrl_min<self.ctrl_max
                and 0<self.nominal_preload<self.effort_limit and self.contact_force_min>0
                and 0<self.confirm_seconds<=self.timeout_seconds and self.loss_seconds>0
                and self.max_extra_compression>0 and self.max_target_deflection>0
                and 0<self.min_pad_fraction<=1 and self.max_com_offset>0 and self.max_passive_speed>0):
            raise ValueError('invalid_contract')


class ClosureController:
    def __init__(self, contract):
        self.c = contract
        self.state = 'closing'
        self.steps = self.good_steps = self.bad_steps = 0
        self.anchor = None
        self.reason = None
        self.last_time = None

    def fail(self, reason):
        self.state='failed';self.reason=reason
        return dict(state=self.state,reason=reason,command=None,anchor=self.anchor,
                    good_steps=self.good_steps,bad_steps=self.bad_steps)

    def update(self, nominal, observation):
        if self.state=='failed':
            return self.fail(self.reason)
        c=self.c;o=observation
        keys=('time','position','velocity','native_force','left_force','right_force',
              'left_pad_fraction','right_pad_fraction','com_offset','passive_speed')
        # Missing COM is expected before any bilateral contact; all other inputs
        # must be finite. Validate atomically before advancing internal state.
        if any(k not in o for k in keys) or not isfinite(nominal):
            raise ValueError('closure_observation_schema')
        if any(not isfinite(o[k]) for k in keys if k!='com_offset'):
            raise ValueError('nonfinite_closure_observation')
        if o['com_offset'] is not None and not isfinite(o['com_offset']):
            raise ValueError('nonfinite_COM')
        if self.last_time is not None and abs(o['time']-self.last_time-c.dt)>1e-9:
            raise ValueError('closure_timestamp_gap')
        self.last_time=o['time'];self.steps+=1
        q=o['position'];v=o['velocity']
        if abs(o['passive_speed'])>c.max_passive_speed:return self.fail('passive_speed')
        if abs(o['native_force'])>c.effort_limit+1e-9:return self.fail('measured_native_effort')
        good=(min(o['left_force'],o['right_force'])>=c.contact_force_min
              and min(o['left_pad_fraction'],o['right_pad_fraction'])>=c.min_pad_fraction
              and o['com_offset'] is not None and 0<=o['com_offset']<=c.max_com_offset)
        if self.state=='closing' and good:
            self.state='confirming';self.anchor=q
        if self.state in ('confirming','holding'):
            if self.anchor-q>c.max_extra_compression:return self.fail('extra_compression')
            if good:self.good_steps+=1;self.bad_steps=0
            else:self.good_steps=0;self.bad_steps+=1
            if self.bad_steps*c.dt>=c.loss_seconds-1e-12:return self.fail('contact_quality_lost')
            if self.good_steps*c.dt>=c.confirm_seconds-1e-12:self.state='holding'
            requested=q-c.nominal_preload/c.kp
        else:
            requested=nominal
        if self.state!='holding' and self.steps*c.dt>=c.timeout_seconds-1e-12:
            return self.fail('closure_timeout')
        # Intersection of native range, target compression envelope and the
        # exact pre-step affine actuator force bounds. Never change model gains.
        low=max(c.ctrl_min,q-c.max_target_deflection,q+(-c.effort_limit+c.kd*v)/c.kp)
        high=min(c.ctrl_max,q+c.max_target_deflection,q+(c.effort_limit+c.kd*v)/c.kp)
        if low>high:return self.fail('no_feasible_native_command')
        command=min(max(requested,low),high)
        predicted=c.kp*(command-q)-c.kd*v
        return dict(state=self.state,reason=None,command=command,requested=requested,
                    predicted_native_force=predicted,effort_limited=abs(command-requested)>1e-12,
                    anchor=self.anchor,good_steps=self.good_steps,bad_steps=self.bad_steps)


def observation(time, position, velocity, native_force, quality, passive_speed):
    return dict(time=float(time),position=float(position),velocity=float(velocity),native_force=float(native_force),
                left_force=quality['left']['force_N'],right_force=quality['right']['force_N'],
                left_pad_fraction=quality['left']['pad_fraction'],right_pad_fraction=quality['right']['pad_fraction'],
                com_offset=quality['contact_com_offset_m'],passive_speed=float(passive_speed))
