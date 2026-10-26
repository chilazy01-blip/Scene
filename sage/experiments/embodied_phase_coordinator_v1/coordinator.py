"""Bounded phase clock and base/body feedback, independent of the simulator.

The caller supplies measured state, task/contact guards, and a geometry-checked
recovery goal. No robot pose is assigned here. A native controller must execute
the returned body-frame velocity, height and unchanged task-space arm goal.
"""
from dataclasses import asdict, dataclass
import math


class CoordinationRejected(ValueError):
    pass


def finite(values):
    return all(math.isfinite(float(v)) for v in values)


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


@dataclass(frozen=True)
class Observation:
    tick: int
    base_xy: tuple
    yaw: float
    height: float
    speed: float
    palm_error: float
    task_ready: bool
    geometry_safe: bool
    in_domain: bool


@dataclass(frozen=True)
class Goal:
    xy: tuple
    yaw: float
    height_command: float
    root_height: float


class Coordinator:
    DT = .02
    MAX_EXTRA_TICKS = 300  # Six seconds per phase, all holds/recovery included.
    STABLE_TICKS = 25

    def __init__(self, stages):
        self.stages = tuple((str(n), int(round((b-a)/self.DT))) for n,a,b in stages)
        if not self.stages or any(n <= 0 for _, n in self.stages):
            raise ValueError('invalid_stages')
        self.stage_index = self.local_tick = self.extra_ticks = self.stable = 0
        self.next_tick = 0
        self.last_height = .74
        self.recovery = None
        self.failure = None
        self.done = False

    @property
    def stage(self):
        return self.stages[min(self.stage_index, len(self.stages)-1)][0]

    def restore(self, state):
        expected = self.snapshot()
        if set(state) != set(expected) or state['version'] != 1 or state['stages'] != expected['stages']:
            raise CoordinationRejected('checkpoint_schema')
        ints = ['stage_index','local_tick','extra_ticks','stable','next_tick']
        if any(type(state[k]) is not int or state[k] < 0 for k in ints):
            raise CoordinationRejected('checkpoint_counters')
        if state['stage_index'] >= len(self.stages) or state['local_tick'] >= self.stages[state['stage_index']][1]:
            raise CoordinationRejected('checkpoint_phase')
        if state['extra_ticks'] > self.MAX_EXTRA_TICKS or state['stable'] > self.STABLE_TICKS:
            raise CoordinationRejected('checkpoint_bounds')
        if not finite([state['last_height']]) or not .64 <= state['last_height'] <= .74:
            raise CoordinationRejected('checkpoint_height')
        r = state['recovery']
        if r is not None:
            self._validate_goal(Goal(**r))
        for k in expected:
            if k not in ['version','stages']:
                setattr(self, k, state[k])

    def snapshot(self):
        return dict(version=1, stages=[list(s) for s in self.stages],
                    stage_index=self.stage_index, local_tick=self.local_tick,
                    extra_ticks=self.extra_ticks, stable=self.stable, next_tick=self.next_tick,
                    last_height=self.last_height, recovery=self.recovery,
                    failure=self.failure, done=self.done)

    @staticmethod
    def _validate_goal(goal):
        if len(goal.xy) != 2 or not finite([*goal.xy,goal.yaw,goal.height_command,goal.root_height]):
            raise CoordinationRejected('goal_shape_finite')
        if not .64 <= goal.height_command <= .74 or not .50 <= goal.root_height <= .90:
            raise CoordinationRejected('goal_native_domain')

    def step(self, observation, goal, *, recovery_goal=None, recovery_certified=False):
        o = observation
        if self.failure or self.done:
            raise CoordinationRejected('closed_coordinator')
        if o.tick != self.next_tick:
            raise CoordinationRejected('nonsequential_observation')
        self._validate_goal(goal)
        if len(o.base_xy) != 2 or not finite([*o.base_xy,o.yaw,o.height,o.speed,o.palm_error]):
            raise CoordinationRejected('observation_shape_finite')
        if o.speed < 0 or o.palm_error < 0:
            raise CoordinationRejected('observation_negative_norm')
        if not o.geometry_safe or not o.in_domain or not .50 <= o.height <= .90:
            self.failure = 'unsafe_or_out_of_domain'
            raise CoordinationRejected(self.failure)
        if self.next_tick >= sum(n+self.MAX_EXTRA_TICKS for _,n in self.stages):
            self.failure = 'total_duration'
            raise CoordinationRejected(self.failure)
        endpoint = self.local_tick == self.stages[self.stage_index][1]-1
        if recovery_goal is not None:
            self._validate_goal(recovery_goal)
            if not endpoint or not recovery_certified or self.recovery is not None:
                raise CoordinationRejected('unverified_or_repeated_recovery')
            if (math.dist(goal.xy,recovery_goal.xy) > .040000001 or
                abs(goal.height_command-recovery_goal.height_command) > .040000001 or
                abs(wrap(goal.yaw-recovery_goal.yaw)) > 1e-9):
                raise CoordinationRejected('recovery_domain')
            self.recovery = asdict(recovery_goal)
        active = Goal(**self.recovery) if self.recovery else goal
        dx,dy = (active.xy[i]-o.base_xy[i] for i in range(2))
        c,s = math.cos(o.yaw),math.sin(o.yaw)
        nav = [max(-.15,min(.15,1.5*(c*dx+s*dy))),
               max(-.08,min(.08,1.5*(-s*dx+c*dy))),
               max(-.15,min(.15,1.5*wrap(active.yaw-o.yaw)))]
        # Native height bounds and 2 cm/s command slew, never direct root motion.
        desired = active.height_command
        self.last_height += max(-.0004,min(.0004,desired-self.last_height))
        pose_ready = (math.hypot(dx,dy) <= .01 and abs(wrap(active.yaw-o.yaw)) <= .01
                      and abs(o.height-active.root_height) <= .015 and o.speed <= .05)
        ready = pose_ready and o.palm_error <= .006 and o.task_ready
        output = dict(tick=o.tick,stage=self.stage,local_tick=self.local_tick,
                      nav=nav,height=self.last_height,rpy=[0.,0.,0.],
                      frame='body_heading',units='SI_rad',recovering=self.recovery is not None,
                      phase_advanced=False,done=False)
        self.next_tick += 1
        if endpoint:
            self.stable = self.stable+1 if ready else 0
            if self.stable >= self.STABLE_TICKS:
                if self.stage_index == len(self.stages)-1:
                    self.done = True
                else:
                    self.stage_index += 1
                    self.local_tick = self.extra_ticks = self.stable = 0
                    self.recovery = None
                output['phase_advanced'] = True
            else:
                self.extra_ticks += 1
                if self.extra_ticks > self.MAX_EXTRA_TICKS:
                    self.extra_ticks = self.MAX_EXTRA_TICKS
                    self.failure = 'phase_recovery_timeout'
                    raise CoordinationRejected(self.failure)
        else:
            self.local_tick += 1
        output['done'] = self.done
        return output
