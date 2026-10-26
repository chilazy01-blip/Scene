"""Measured progress with latched braking and bounded recovery."""
from dataclasses import dataclass
from ..repair_v2.progress import ControlRejected
import math


@dataclass(frozen=True)
class MotionLimits:
    dt: float = .02
    joint_velocity: float = .5
    joint_acceleration: float = 2.0
    tracking_error: float = .04
    max_pause_seconds: float = 2.0
    recovery_error: float = .02
    recovery_seconds: float = .1
    minimum_progress: float = .0001
    ik_position: float = .005
    ik_rotation: float = .05
    ik_condition: float = 1e5


def validate_ik(errors, limits=MotionLimits()):
    if set(errors) != {"left", "right"}:
        raise ControlRejected("missing_ik_evidence")
    for side, e in errors.items():
        v = [e.get(k, float("nan")) for k in ("position", "rotation", "condition")]
        if not all(math.isfinite(x) for x in v) or any(x < 0 for x in v):
            raise ControlRejected("invalid_ik_evidence:"+side)
        if v[0] > limits.ik_position or v[1] > limits.ik_rotation or v[2] > limits.ik_condition:
            raise ControlRejected("ik_unreachable_or_ill_conditioned:"+side)


class CoordinatedPath:
    """Rest-to-rest linear segments, with tracking-triggered bounded braking.

    All joint channels share scalar progress. A halt keeps braking at the same
    acceleration limit, and validates the complete remaining stopping corridor.
    A corridor failure raises before issuing a new command; the caller exits the
    simulated trial rather than executing a guessed emergency manoeuvre.
    """
    def __init__(self, waypoints, limits=MotionLimits(), tracking_waypoints=None):
        self.path = [list(map(float, row)) for row in waypoints]
        if len(self.path) < 2 or not self.path[0] or any(len(row) != len(self.path[0]) or not all(math.isfinite(x) for x in row) for row in self.path):
            raise ValueError("invalid_path")
        if any(not math.isfinite(v) or v <= 0 for v in vars(limits).values()):
            raise ValueError("invalid_motion_limits")
        self.limits = limits
        self.tracking_path = self.path if tracking_waypoints is None else [list(map(float,row)) for row in tracking_waypoints]
        if len(self.tracking_path) != len(self.path) or any(len(row) != len(self.path[0]) or not all(math.isfinite(x) for x in row) for row in self.tracking_path):
            raise ValueError("invalid_tracking_path")
        if limits.recovery_error >= limits.tracking_error:
            raise ValueError("invalid_recovery_threshold")
        for a,b,ta,tb in zip(self.path,self.path[1:],self.tracking_path,self.tracking_path[1:]):
            if max(abs(y-x) for x,y in zip(a,b)) < 1e-12 and max(abs(y-x) for x,y in zip(ta,tb)) > 1e-12:
                raise ValueError("unactuated_tracking_segment")
        self.braking=False
        self.last_lag=float('inf')
        self.recovered=0.
        self.elapsed=self.travel=0.
        self.history=[]
        self.expected_actual = self.tracking_path[0].copy()
        self.segment = 0
        self.u = self.speed = self.pause = 0.
        self.last = self.path[0].copy()
        self.last_velocity = [0.]*len(self.last)

    @property
    def finished(self):
        return self.segment == len(self.path)-1 and self.last_lag <= self.limits.recovery_error and not self.braking

    def step(self, actual, swept_safe):
        actual = list(map(float, actual))
        if len(actual) != len(self.last) or not all(math.isfinite(x) for x in actual):
            raise ControlRejected("invalid_actual_state")
        l = self.limits
        lag = max(abs(a-b) for a,b in zip(actual,self.expected_actual))
        self.last_lag=lag
        self.elapsed += l.dt
        if lag > l.tracking_error:
            self.braking=True
        if self.braking:
            self.pause += l.dt
            self.recovered = self.recovered+l.dt if lag <= l.recovery_error else 0.
            if self.recovered+1e-12 >= l.recovery_seconds:
                self.braking=False
                self.pause=self.recovered=0.
            elif self.pause > l.max_pause_seconds:
                raise ControlRejected("tracking_timeout")
        # Once the path ends, nominal travel must stay zero. Measured terminal
        # tracking is still required; the tracking timeout and the worker's
        # frozen total-command bound continue to limit that settling period.
        if self.segment < len(self.path)-1:
            self.history.append((self.elapsed,self.travel))
            while len(self.history)>1 and self.history[1][0]<=self.elapsed-l.max_pause_seconds:
                self.history.pop(0)
            if (self.elapsed-self.history[0][0]>=l.max_pause_seconds-1e-9
                    and self.travel-self.history[0][1]<l.minimum_progress):
                raise ControlRejected("path_stagnation")
        if self.segment == len(self.path)-1:
            return self.last.copy(), dict(finished=self.finished, lag=lag, progress=1., braking=self.braking)
        start, end = self.path[self.segment:self.segment+2]
        delta = [b-a for a,b in zip(start,end)]
        scale = max(map(abs,delta))
        if scale < 1e-12:
            self.expected_actual=self.tracking_path[self.segment+1].copy()
            self.segment += 1
            self.u = self.speed = 0.
            return self.last.copy(), dict(finished=False, lag=lag, progress=0.)
        vmax, amax = l.joint_velocity/scale, l.joint_acceleration/scale
        remaining = max(0., 1.-self.u)
        # Conservative discrete stopping envelope: v*dt + v^2/(2a) <= remaining.
        stopping_speed = max(0., math.sqrt((amax*l.dt)**2 + 2*amax*remaining)-amax*l.dt)
        desired = min(vmax, stopping_speed) if not self.braking else 0.
        speed = min(max(desired,self.speed-amax*l.dt),self.speed+amax*l.dt)
        next_u = self.u+speed*l.dt
        if next_u > 1.+1e-9:
            raise ControlRejected("path_stopping_envelope")
        command = [a+min(1.,next_u)*b for a,b in zip(start,delta)]
        velocity = [(a-b)/l.dt for a,b in zip(command,self.last)]
        acceleration = [(a-b)/l.dt for a,b in zip(velocity,self.last_velocity)]
        # Near the endpoint settle exactly, only if the final move meets both limits.
        if remaining*scale < 1e-6 and self.speed*scale < l.joint_acceleration*l.dt:
            command = end.copy()
            velocity = [(a-b)/l.dt for a,b in zip(command,self.last)]
            acceleration = [(a-b)/l.dt for a,b in zip(velocity,self.last_velocity)]
            next_u = 1.
        if max(map(abs,velocity)) > l.joint_velocity+1e-8 or max(map(abs,acceleration)) > l.joint_acceleration+1e-8:
            raise ControlRejected("command_derivative_limit:"+str(dict(segment=self.segment,progress=self.u,
                velocity=max(map(abs,velocity)),acceleration=max(map(abs,acceleration)))))
        stop_u = min(1., next_u+speed*l.dt+speed*speed/(2*amax))
        stop = [a+stop_u*b for a,b in zip(start,delta)]
        if not swept_safe(self.last.copy(), command.copy(), stop):
            raise ControlRejected("swept_or_stopping_corridor")
        self.travel += max(abs(a-b) for a,b in zip(command,self.last))
        self.last, self.last_velocity = command.copy(), velocity
        ta,tb = self.tracking_path[self.segment:self.segment+2]
        self.expected_actual = [a+min(1.,next_u)*(b-a) for a,b in zip(ta,tb)]
        self.u, self.speed = next_u, speed
        # Require an actual zero-velocity command before changing segment direction.
        # Treating a small residual velocity as zero adds it to the next acceleration.
        if next_u >= 1. and max(map(abs,velocity)) <= 1e-12:
            self.segment += 1
            self.u = self.speed = 0.
        return command, dict(finished=False, lag=lag, progress=next_u,
                             segment=self.segment, peak_velocity=float(max(map(abs,velocity))),
                             peak_acceleration=float(max(map(abs,acceleration))), braking=self.braking, pause_seconds=self.pause, recovery_seconds=self.recovered)


class ManipulationState:
    """Transitions are observations, never source-demo phase or elapsed time alone."""
    def __init__(self, dt=.02):
        self.phase = "pick"
        self.dt = dt
        self.stable = 0.

    def update(self, *, grasped, slipped, lifted, at_standoff, settled,
               placement_ready, supported, released, withdrawal_done, terminal_passed):
        if slipped or (self.phase in {"carry", "settle", "place"} and not grasped and not supported):
            raise ControlRejected("grasp_lost_or_slipping")
        if self.phase == "pick" and grasped and lifted:
            self.phase = "carry"
        elif self.phase == "carry" and at_standoff:
            self.phase = "settle"
        elif self.phase == "settle":
            self.stable = self.stable+self.dt if settled else 0.
            if self.stable >= .3 and placement_ready:
                self.phase = "place"
        elif self.phase == "place" and supported:
            self.phase = "release"
        elif self.phase == "release" and supported and released:
            self.phase = "withdraw"
        elif self.phase == "withdraw" and supported and released and withdrawal_done:
            self.phase = "hold"
        elif self.phase == "hold" and terminal_passed:
            self.phase = "complete"
        return self.phase


def grasp_state(left_contacts, right_contacts, relative_translation, relative_speed,
                hand_vertical_load, required_load, *, displacement_limit, speed_limit, load_tolerance=.2):
    values = [left_contacts, right_contacts, relative_translation, relative_speed,
              hand_vertical_load, required_load, displacement_limit, speed_limit]
    if not all(math.isfinite(v) for v in values) or min(values) < 0 or required_load <= 0:
        raise ControlRejected("invalid_grasp_evidence")
    touching = left_contacts > 0 and right_contacts > 0
    slipped = relative_translation > displacement_limit or relative_speed > speed_limit
    loaded = hand_vertical_load >= (1-load_tolerance)*required_load
    return dict(grasped=touching and loaded and not slipped, slipped=slipped,
                both_hands=touching, carries_load=loaded)
